import asyncio
import websockets
import json
import subprocess
import os
import sys
import platform

BASE_DIR = "workspace"  # Directory to store files
os.makedirs(BASE_DIR, exist_ok=True)

active_files = {}  # {filename: {clients}}
file_contents = {}  # {filename: content}
file_locks = {}  # {filename: websocket} - Tracks which client has exclusive access

async def execute_code(filename, websocket, input_queue):
    """Runs code securely and returns output"""
    filepath = os.path.join(BASE_DIR, filename)
    extension = filename.split(".")[-1]

    try:
        if extension == "py":
            process = await asyncio.create_subprocess_exec(
                sys.executable, filepath,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        elif extension == "c":
            exe_file = filepath.replace(".c", ".exe" if platform.system() == "Windows" else "")
            compile_result = subprocess.run(["gcc", filepath, "-o", exe_file], capture_output=True, text=True)
            if compile_result.returncode != 0:
                await websocket.send(json.dumps({
                    "command": "OUTPUT", 
                    "output": f"Compilation error: {compile_result.stderr}",
                    "finished": True
                }))
                return
                
            process = await asyncio.create_subprocess_exec(
                exe_file,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        elif extension == "java":
            class_name = os.path.basename(filepath).replace(".java", "")
            compile_result = subprocess.run(["javac", filepath], capture_output=True, text=True)
            if compile_result.returncode != 0:
                await websocket.send(json.dumps({
                    "command": "OUTPUT", 
                    "output": f"Compilation error: {compile_result.stderr}",
                    "finished": True
                }))
                return
                
            process = await asyncio.create_subprocess_exec(
                "java", "-cp", BASE_DIR, class_name,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
        else:
            await websocket.send(json.dumps({
                "command": "OUTPUT", 
                "output": "Unsupported file type",
                "finished": True
            }))
            return

        # Notify program started
        await websocket.send(json.dumps({"command": "PROGRAM_STARTED"}))
        
        # Create tasks for handling stdin/stdout/stderr
        async def handle_stdout():
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                try:
                    await websocket.send(json.dumps({
                        "command": "OUTPUT",
                        "output": line.decode(),
                        "finished": False
                    }))
                except websockets.exceptions.ConnectionClosed:
                    break
                
        async def handle_stderr():
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                try:
                    await websocket.send(json.dumps({
                        "command": "OUTPUT",
                        "output": line.decode(),
                        "finished": False
                    }))
                except websockets.exceptions.ConnectionClosed:
                    break
                
        async def handle_stdin():
            while process.returncode is None:
                if not input_queue.empty():
                    try:
                        user_input = await input_queue.get()
                        process.stdin.write(f"{user_input}\n".encode())
                        await process.stdin.drain()
                    except Exception:
                        break
                await asyncio.sleep(0.1)
            
        # Start tasks
        stdout_task = asyncio.create_task(handle_stdout())
        stderr_task = asyncio.create_task(handle_stderr())
        stdin_task = asyncio.create_task(handle_stdin())
        
        # Wait for process to complete
        await process.wait()
        
        # Clean up tasks
        stdin_task.cancel()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        
        # Notify program finished
        try:
            await websocket.send(json.dumps({"command": "PROGRAM_FINISHED", "finished": True}))
        except websockets.exceptions.ConnectionClosed:
            pass
        
    except Exception as e:
        try:
            await websocket.send(json.dumps({
                "command": "OUTPUT", 
                "output": f"Error: {str(e)}",
                "finished": True
            }))
        except websockets.exceptions.ConnectionClosed:
            pass

async def handler(websocket):
    # Create input queue for each client
    input_queue = asyncio.Queue()
    
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                command = data.get("command")
                filename = data.get("filename")
                
                if command == "OPEN":
                    if not filename:
                        await websocket.send(json.dumps({"command": "ERROR", "message": "No filename provided"}))
                        continue
                        
                    # Check if file is locked by another client
                    if filename in file_locks and file_locks[filename] != websocket:
                        await websocket.send(json.dumps({
                            "command": "ERROR", 
                            "message": "File is being edited by another user"
                        }))
                        continue
                        
                    filepath = os.path.join(BASE_DIR, filename)
                    if filename not in file_contents:
                        try:
                            with open(filepath, "r", encoding="utf-8") as f:
                                file_contents[filename] = f.read()
                        except FileNotFoundError:
                            file_contents[filename] = ""

                    if filename not in active_files:
                        active_files[filename] = set()

                    active_files[filename].add(websocket)
                    # Lock the file for this client
                    file_locks[filename] = websocket
                    
                    await websocket.send(json.dumps({"command": "LOAD", "content": file_contents[filename]}))

                elif command == "EDIT":
                    if not filename:
                        await websocket.send(json.dumps({"command": "ERROR", "message": "No filename provided"}))
                        continue
                        
                    # Check if client has lock on file
                    if filename not in file_locks or file_locks[filename] != websocket:
                        await websocket.send(json.dumps({
                            "command": "ERROR", 
                            "message": "You don't have exclusive access to edit this file"
                        }))
                        continue
                        
                    filepath = os.path.join(BASE_DIR, filename)
                    new_content = data.get("content", "")
                    file_contents[filename] = new_content
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(new_content)  # Save automatically

                elif command == "RUN":
                    if not filename:
                        await websocket.send(json.dumps({"command": "ERROR", "message": "No filename provided"}))
                        continue
                    
                    # Clear input queue before starting
                    while not input_queue.empty():
                        await input_queue.get()
                        
                    # Execute code in separate task
                    asyncio.create_task(execute_code(filename, websocket, input_queue))
                
                elif command == "PROGRAM_INPUT":
                    # Add user input to the queue
                    user_input = data.get("input", "")
                    await input_queue.put(user_input)

                elif command == "CLOSE":
                    if not filename:
                        continue
                        
                    # Release lock if this client has it
                    if filename in file_locks and file_locks[filename] == websocket:
                        del file_locks[filename]
                        
                    if filename in active_files:
                        active_files[filename].discard(websocket)
                        if not active_files[filename]:
                            del active_files[filename]
                        
                elif command == "LIST_FILES":
                    # Get list of files in workspace directory
                    files = [f for f in os.listdir(BASE_DIR) if os.path.isfile(os.path.join(BASE_DIR, f))]
                    
                    # Add lock status information
                    file_status = []
                    for f in files:
                        locked = f in file_locks and file_locks[f] != websocket
                        file_status.append({"name": f, "locked": locked})
                        
                    await websocket.send(json.dumps({
                        "command": "FILES_LIST", 
                        "files": files,
                        "file_status": file_status
                    }))
                    
                elif command == "CREATE_FILE":
                    new_filename = data.get("filename")
                    if not new_filename:
                        await websocket.send(json.dumps({"command": "ERROR", "message": "No filename provided"}))
                        continue
                        
                    # Create an empty file
                    new_filepath = os.path.join(BASE_DIR, new_filename)
                    with open(new_filepath, "w", encoding="utf-8") as f:
                        pass
                        
                    # Send confirmation
                    await websocket.send(json.dumps({"command": "FILE_CREATED", "filename": new_filename}))
                
                elif command == "DELETE_FILE":
                    if not filename:
                        await websocket.send(json.dumps({"command": "ERROR", "message": "No filename provided"}))
                        continue
                    
                    # Check if file is locked by another client
                    if filename in file_locks and file_locks[filename] != websocket:
                        await websocket.send(json.dumps({
                            "command": "ERROR", 
                            "message": "Cannot delete file - it's being edited by another user"
                        }))
                        continue
                    
                    # Delete the file
                    filepath = os.path.join(BASE_DIR, filename)
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        
                        # Clean up data structures
                        if filename in file_contents:
                            del file_contents[filename]
                        if filename in file_locks:
                            del file_locks[filename]
                        if filename in active_files:
                            del active_files[filename]
                        
                        await websocket.send(json.dumps({"command": "FILE_DELETED", "filename": filename}))
                    else:
                        await websocket.send(json.dumps({
                            "command": "ERROR", 
                            "message": f"File {filename} not found"
                        }))
                    
            except json.JSONDecodeError:
                print(f"Invalid JSON received")
            except Exception as e:
                print(f"Error handling message: {e}")
                try:
                    await websocket.send(json.dumps({"command": "ERROR", "message": str(e)}))
                except websockets.exceptions.ConnectionClosed:
                    break
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        # Clean up all file references and locks for this websocket
        for filename in list(active_files.keys()):
            if websocket in active_files[filename]:
                active_files[filename].discard(websocket)
                if not active_files[filename]:
                    del active_files[filename]
        
        # Release any locks held by this client
        for filename in list(file_locks.keys()):
            if file_locks[filename] == websocket:
                del file_locks[filename]

async def main():
    host = "0.0.0.0"
    port = 8765
    print(f"Starting server on {host}:{port}")
    
    # Set higher heartbeat interval and timeout
    try:
        async with websockets.serve(
            handler, 
            host, 
            port,
            ping_interval=30,
            ping_timeout=60
        ):
            await asyncio.Future()  # Keep server running
    except OSError as e:
        print(f"Failed to start server: {e}")
        if "address already in use" in str(e).lower():
            print("Port 8765 is already in use. Please close the application using that port and try again.")
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nServer stopped by user")