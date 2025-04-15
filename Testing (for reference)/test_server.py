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

async def execute_code(filename):
    """Runs code securely and returns output"""
    filepath = os.path.join(BASE_DIR, filename)
    extension = filename.split(".")[-1]

    try:
        if extension == "py":
            # Use sys.executable to get the current Python interpreter
            result = subprocess.run([sys.executable, filepath], capture_output=True, text=True, timeout=5)
        elif extension == "c":
            exe_file = filepath.replace(".c", ".exe" if platform.system() == "Windows" else "")
            compile_result = subprocess.run(["gcc", filepath, "-o", exe_file], capture_output=True, text=True)
            if compile_result.returncode != 0:
                return f"Compilation error: {compile_result.stderr}"
            result = subprocess.run([exe_file], capture_output=True, text=True, timeout=5)
        elif extension == "java":
            class_name = os.path.basename(filepath).replace(".java", "")
            compile_result = subprocess.run(["javac", filepath], capture_output=True, text=True)
            if compile_result.returncode != 0:
                return f"Compilation error: {compile_result.stderr}"
            result = subprocess.run(["java", "-cp", BASE_DIR, class_name], capture_output=True, text=True, timeout=5)
        else:
            return "Unsupported file type"

        if result.returncode != 0:
            return f"Execution error: {result.stderr}"
        return result.stdout or result.stderr
    except subprocess.TimeoutExpired:
        return "Execution timed out after 5 seconds"
    except Exception as e:
        return str(e)

async def handler(websocket):
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                command = data.get("command")
                
                # Only create filepath if the command actually needs a filename
                filename = data.get("filename")
                
                if command == "OPEN":
                    if not filename:
                        await websocket.send(json.dumps({"command": "ERROR", "message": "No filename provided"}))
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
                    await websocket.send(json.dumps({"command": "LOAD", "content": file_contents[filename]}))

                elif command == "EDIT":
                    if not filename:
                        await websocket.send(json.dumps({"command": "ERROR", "message": "No filename provided"}))
                        continue
                        
                    filepath = os.path.join(BASE_DIR, filename)
                    new_content = data.get("content", "")
                    file_contents[filename] = new_content
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(new_content)  # Save automatically

                    for client in active_files.get(filename, set()):
                        if client != websocket:
                            try:
                                await client.send(json.dumps({"command": "UPDATE", "content": new_content}))
                            except websockets.exceptions.ConnectionClosed:
                                active_files[filename].discard(client)

                elif command == "RUN":
                    if not filename:
                        await websocket.send(json.dumps({"command": "ERROR", "message": "No filename provided"}))
                        continue
                        
                    output = await execute_code(filename)
                    for client in active_files.get(filename, set()):
                        try:
                            await client.send(json.dumps({"command": "OUTPUT", "output": output}))
                        except websockets.exceptions.ConnectionClosed:
                            active_files[filename].discard(client)

                elif command == "CLOSE":
                    if not filename:
                        continue
                        
                    active_files.get(filename, set()).discard(websocket)
                    if filename in active_files and not active_files[filename]:
                        del active_files[filename]
                        
                elif command == "LIST_FILES":
                    # Get list of files in workspace directory
                    files = [f for f in os.listdir(BASE_DIR) if os.path.isfile(os.path.join(BASE_DIR, f))]
                    await websocket.send(json.dumps({"command": "FILES_LIST", "files": files}))
                    
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
                    
            except json.JSONDecodeError:
                print(f"Invalid JSON received: {message}")
            except Exception as e:
                print(f"Error handling message: {e}")
    except websockets.exceptions.ConnectionClosed:
        # Clean up all file references to this websocket
        for filename in list(active_files.keys()):
            if websocket in active_files[filename]:
                active_files[filename].discard(websocket)
                if not active_files[filename]:
                    del active_files[filename]

async def main():
    host = "0.0.0.0"  # Changed from 0.0.0.0 for better cross-platform compatibility
    port = 8765
    print(f"Starting server on {host}:{port}")
    try:
        async with websockets.serve(handler, host, port):
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