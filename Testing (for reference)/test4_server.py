#!/usr/bin/env python3
import asyncio
import websockets
import os
import json
import subprocess
import signal
import sys
from pathlib import Path

WORKSPACE_DIR = "workspace"

class CodeServer:
    def __init__(self, host="localhost", port=8765):
        self.host = host
        self.port = port
        self.active_sessions = {}
        
        # Ensure workspace directory exists
        Path(WORKSPACE_DIR).mkdir(exist_ok=True)
        
    async def start(self):
        """Start the WebSocket server"""
        print(f"Server starting on {self.host}:{self.port}")
        
        # Handle graceful shutdown
        loop = asyncio.get_event_loop()
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.shutdown()))
            
        async with websockets.serve(self.handle_client, self.host, self.port, ping_interval=None):
            await asyncio.Future()  # Run forever
            
    async def shutdown(self):
        """Gracefully shutdown the server"""
        print("\nShutting down server...")
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        [task.cancel() for task in tasks]
        await asyncio.gather(*tasks, return_exceptions=True)
        asyncio.get_event_loop().stop()
        
    async def handle_client(self, websocket):
        """Handle a client connection"""
        client_id = id(websocket)
        self.active_sessions[client_id] = websocket
        print(f"Client connected: {client_id}")
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    action = data.get("action")
                    
                    if action == "list_files":
                        await self.list_files(websocket)
                    elif action == "get_file":
                        await self.get_file(websocket, data)
                    elif action == "save_file":
                        await self.save_file(websocket, data)
                    elif action == "create_file":
                        await self.create_file(websocket, data)
                    elif action == "run_file":
                        await self.run_file(websocket, data)
                    else:
                        await websocket.send(json.dumps({
                            "status": "error",
                            "message": f"Unknown action: {action}"
                        }))
                except json.JSONDecodeError:
                    await websocket.send(json.dumps({
                        "status": "error",
                        "message": "Invalid JSON format"
                    }))
        except websockets.exceptions.ConnectionClosed:
            print(f"Client disconnected: {client_id}")
        finally:
            if client_id in self.active_sessions:
                del self.active_sessions[client_id]
                
    async def list_files(self, websocket):
        """List all code files in the workspace"""
        files = []
        for file in os.listdir(WORKSPACE_DIR):
            file_path = os.path.join(WORKSPACE_DIR, file)
            if os.path.isfile(file_path) and not file.endswith(".out"):
                ext = os.path.splitext(file)[1]
                if ext in [".py", ".c", ".cpp", ""]:
                    files.append(file)
                    
        await websocket.send(json.dumps({
            "status": "success",
            "action": "list_files",
            "files": files
        }))
        
    async def get_file(self, websocket, data):
        """Get the contents of a file"""
        filename = data.get("filename")
        file_path = os.path.join(WORKSPACE_DIR, filename)
        
        if not os.path.exists(file_path) or not os.path.isfile(file_path):
            await websocket.send(json.dumps({
                "status": "error",
                "action": "get_file",
                "message": f"File {filename} does not exist"
            }))
            return
            
        try:
            with open(file_path, "r") as f:
                content = f.read()
                
            await websocket.send(json.dumps({
                "status": "success",
                "action": "get_file",
                "filename": filename,
                "content": content
            }))
        except Exception as e:
            await websocket.send(json.dumps({
                "status": "error",
                "action": "get_file",
                "message": f"Error reading file: {str(e)}"
            }))
            
    async def save_file(self, websocket, data):
        """Save content to a file"""
        filename = data.get("filename")
        content = data.get("content")
        file_path = os.path.join(WORKSPACE_DIR, filename)
        
        try:
            with open(file_path, "w") as f:
                f.write(content)
                
            await websocket.send(json.dumps({
                "status": "success",
                "action": "save_file",
                "message": f"File {filename} saved successfully"
            }))
        except Exception as e:
            await websocket.send(json.dumps({
                "status": "error",
                "action": "save_file",
                "message": f"Error saving file: {str(e)}"
            }))
            
    async def create_file(self, websocket, data):
        """Create a new file"""
        filename = data.get("filename")
        file_type = data.get("type", "py")
        
        if not filename:
            await websocket.send(json.dumps({
                "status": "error",
                "action": "create_file",
                "message": "Filename is required"
            }))
            return
            
        # Add extension if not provided
        if not filename.endswith(f".{file_type}"):
            filename = f"{filename}.{file_type}"
            
        file_path = os.path.join(WORKSPACE_DIR, filename)
        
        # Check if file already exists
        if os.path.exists(file_path):
            await websocket.send(json.dumps({
                "status": "error",
                "action": "create_file",
                "message": f"File {filename} already exists"
            }))
            return
            
        try:
            # Create empty file
            with open(file_path, "w") as f:
                if file_type == "c":
                    f.write('#include <stdio.h>\n\nint main() {\n    printf("Hello, World!\\n");\n    return 0;\n}\n')
                elif file_type == "py":
                    f.write('print("Hello, World!")\n')
                    
            await websocket.send(json.dumps({
                "status": "success",
                "action": "create_file",
                "filename": filename,
                "message": f"File {filename} created successfully"
            }))
        except Exception as e:
            await websocket.send(json.dumps({
                "status": "error",
                "action": "create_file",
                "message": f"Error creating file: {str(e)}"
            }))
            
    async def run_file(self, websocket, data):
        """Run a code file and stream the output back to the client"""
        filename = data.get("filename")
        input_data = data.get("input", "")
        file_path = os.path.join(WORKSPACE_DIR, filename)
        
        if not os.path.exists(file_path):
            await websocket.send(json.dumps({
                "status": "error",
                "action": "run_file",
                "message": f"File {filename} does not exist"
            }))
            return
            
        try:
            ext = os.path.splitext(filename)[1]
            
            if ext == ".c":
                # Compile and run C file
                output_file = os.path.join(WORKSPACE_DIR, f"{os.path.splitext(filename)[0]}.out")
                compile_cmd = ["gcc", file_path, "-o", output_file]
                
                compile_process = await asyncio.create_subprocess_exec(
                    *compile_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                _, stderr = await compile_process.communicate()
                
                if compile_process.returncode != 0:
                    await websocket.send(json.dumps({
                        "status": "error",
                        "action": "run_file",
                        "message": f"Compilation error: {stderr.decode()}"
                    }))
                    return
                    
                cmd = [output_file]
            elif ext == ".py":
                # Run Python file
                cmd = ["python3", file_path]
            else:
                await websocket.send(json.dumps({
                    "status": "error",
                    "action": "run_file",
                    "message": f"Unsupported file type: {ext}"
                }))
                return
                
            # Run the program with input if provided
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE if input_data else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            if input_data:
                stdout, stderr = await process.communicate(input_data.encode())
            else:
                stdout, stderr = await process.communicate()
                
            result = stdout.decode()
            error = stderr.decode()
            
            await websocket.send(json.dumps({
                "status": "success",
                "action": "run_file",
                "result": result,
                "error": error,
                "exit_code": process.returncode
            }))
        except Exception as e:
            await websocket.send(json.dumps({
                "status": "error",
                "action": "run_file",
                "message": f"Error running file: {str(e)}"
            }))

if __name__ == "__main__":
    server = CodeServer()
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("Server stopped")
        sys.exit(0)