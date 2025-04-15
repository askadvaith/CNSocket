import asyncio
import websockets
import json
import os
import sys
import curses
import threading

# Configure server address
SERVER_URI = "ws://localhost:8765"

# ANSI escape sequences for formatting
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_UNDERLINE = "\033[4m"
ANSI_RED = "\033[91m"
ANSI_GREEN = "\033[92m"
ANSI_BLUE = "\033[94m"

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_header(text):
    print(f"{ANSI_BOLD}{text}{ANSI_RESET}")

def print_error(text):
    print(f"{ANSI_BOLD}{ANSI_RED}ERROR: {text}{ANSI_RESET}")

def print_success(text):
    print(f"{ANSI_GREEN}{text}{ANSI_RESET}")

class VimEditor:
    def __init__(self, stdscr, content=""):
        self.stdscr = stdscr
        self.lines = content.split('\n')
        if not self.lines:
            self.lines = [""]
        self.cursor_y = 0
        self.cursor_x = 0
        self.top_line = 0
        self.mode = "normal"  # normal, insert
        self.status_message = "-- NORMAL MODE --"
        self.command_buffer = ""
        
    def run(self):
        curses.curs_set(1)  # Show cursor
        curses.use_default_colors()
        curses.start_color()
        self.height, self.width = self.stdscr.getmaxyx()
        
        while True:
            self.display()
            key = self.stdscr.getch()
            
            if self.mode == "normal":
                self.handle_normal_mode(key)
            elif self.mode == "insert":
                self.handle_insert_mode(key)
            elif self.mode == "command":
                self.handle_command_mode(key)
                
            if self.command_buffer == ":q":
                self.command_buffer = ""
                return ''.join(line + '\n' for line in self.lines).rstrip('\n')
            
            if self.command_buffer == ":w":
                self.command_buffer = ""
                self.status_message = "File saved"
                return None
                
            if self.command_buffer == ":r":
                self.command_buffer = ""
                self.status_message = "Running file..."
                return "run"
    
    def display(self):
        self.stdscr.clear()
        self.height, self.width = self.stdscr.getmaxyx()
        
        # Display lines
        for i in range(min(self.height - 2, len(self.lines) - self.top_line)):
            line = self.lines[i + self.top_line]
            self.stdscr.addstr(i, 0, line[:self.width-1])
            
        # Status line
        status_line = f" {self.status_message} | Line {self.cursor_y+1}/{len(self.lines)}"
        self.stdscr.addstr(self.height-2, 0, status_line[:self.width-1], curses.A_REVERSE)
        
        # Command line
        if self.mode == "command":
            self.stdscr.addstr(self.height-1, 0, self.command_buffer, curses.A_BOLD)
        
        # Position cursor
        cursor_screen_y = self.cursor_y - self.top_line
        if 0 <= cursor_screen_y < self.height - 2:
            self.stdscr.move(cursor_screen_y, min(self.cursor_x, len(self.lines[self.cursor_y])))
        
        self.stdscr.refresh()
    
    def handle_normal_mode(self, key):
        if key == ord('i'):
            self.mode = "insert"
            self.status_message = "-- INSERT MODE --"
        elif key == ord(':'):
            self.mode = "command"
            self.command_buffer = ":"
        elif key == ord('h'):  # Left
            if self.cursor_x > 0:
                self.cursor_x -= 1
        elif key == ord('j'):  # Down
            if self.cursor_y < len(self.lines) - 1:
                self.cursor_y += 1
                self.cursor_x = min(self.cursor_x, len(self.lines[self.cursor_y]))
                # Scroll down if needed
                if self.cursor_y >= self.top_line + self.height - 2:
                    self.top_line = self.cursor_y - (self.height - 3)
        elif key == ord('k'):  # Up
            if self.cursor_y > 0:
                self.cursor_y -= 1
                self.cursor_x = min(self.cursor_x, len(self.lines[self.cursor_y]))
                # Scroll up if needed
                if self.cursor_y < self.top_line:
                    self.top_line = self.cursor_y
        elif key == ord('l'):  # Right
            if self.cursor_x < len(self.lines[self.cursor_y]):
                self.cursor_x += 1
        elif key == ord('G'):  # Go to end
            self.cursor_y = len(self.lines) - 1
            self.cursor_x = 0
            # Adjust scroll position
            if len(self.lines) > self.height - 2:
                self.top_line = max(0, len(self.lines) - (self.height - 2))
    
    def handle_insert_mode(self, key):
        if key == 27:  # ESC
            self.mode = "normal"
            self.status_message = "-- NORMAL MODE --"
        elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:  # Backspace
            if self.cursor_x > 0:
                self.lines[self.cursor_y] = (
                    self.lines[self.cursor_y][:self.cursor_x-1] + 
                    self.lines[self.cursor_y][self.cursor_x:]
                )
                self.cursor_x -= 1
            elif self.cursor_y > 0:  # At beginning of line, merge with previous line
                self.cursor_x = len(self.lines[self.cursor_y-1])
                self.lines[self.cursor_y-1] += self.lines[self.cursor_y]
                self.lines.pop(self.cursor_y)
                self.cursor_y -= 1
        elif key == 10 or key == 13:  # Enter
            # Split the line at cursor position
            new_line = self.lines[self.cursor_y][self.cursor_x:]
            self.lines[self.cursor_y] = self.lines[self.cursor_y][:self.cursor_x]
            self.lines.insert(self.cursor_y + 1, new_line)
            self.cursor_y += 1
            self.cursor_x = 0
            # Scroll if needed
            if self.cursor_y >= self.top_line + self.height - 2:
                self.top_line += 1
        else:
            # Insert character at cursor position
            try:
                char = chr(key)
                self.lines[self.cursor_y] = (
                    self.lines[self.cursor_y][:self.cursor_x] + 
                    char + 
                    self.lines[self.cursor_y][self.cursor_x:]
                )
                self.cursor_x += 1
            except:
                pass  # Ignore non-character keys
    
    def handle_command_mode(self, key):
        if key == 27:  # ESC
            self.mode = "normal"
            self.command_buffer = ""
            self.status_message = "-- NORMAL MODE --"
        elif key == 10 or key == 13:  # Enter
            if self.command_buffer == ":q" or self.command_buffer == ":w" or self.command_buffer == ":r":
                return  # Let the main function handle these
            self.mode = "normal"
            self.command_buffer = ""
            self.status_message = "-- NORMAL MODE --"
        elif key == curses.KEY_BACKSPACE or key == 127 or key == 8:  # Backspace
            if len(self.command_buffer) > 1:  # Keep the initial ':'
                self.command_buffer = self.command_buffer[:-1]
        else:
            try:
                char = chr(key)
                self.command_buffer += char
            except:
                pass  # Ignore non-character keys

async def file_selection_screen(websocket):
    while True:
        clear_screen()
        print_header("File Selection")
        print("1. List files")
        print("2. Create new file")
        print("3. Exit")
        choice = input("Enter your choice (1-3): ")

        if choice == '1':
            await list_files(websocket)
        elif choice == '2':
            await create_new_file(websocket)
        elif choice == '3':
            return False
        else:
            print_error("Invalid choice. Please try again.")
            await asyncio.sleep(1)

async def list_files(websocket):
    await websocket.send(json.dumps({"command": "LIST_FILES"}))
    response = await websocket.recv()
    data = json.loads(response)
    files = data.get("files", [])
    file_status = data.get("file_status", [])
    
    clear_screen()
    print_header("Available Files:")
    for i, file_info in enumerate(file_status, 1):
        file = file_info["name"]
        locked = file_info["locked"]
        status = f"{ANSI_RED}[LOCKED]{ANSI_RESET}" if locked else ""
        print(f"{i}. {file} {status}")
    print("\n0. Back")
    print("\nUse arrow keys to navigate, Enter to select, Del to delete a file")
    
    # Implement simple keyboard navigation for file selection
    selected = 0
    while True:
        key = input("Enter file number to edit, 0 to go back, or press Del + number to delete: ")
        
        if key == '0':
            return
            
        if key.startswith('Del') or key.lower().startswith('d'):
            try:
                file_num = int(key.split()[-1]) - 1
                if 0 <= file_num < len(files):
                    filename = files[file_num]
                    # Check if locked
                    if file_status[file_num]["locked"]:
                        print_error(f"Cannot delete '{filename}' - file is locked by another user.")
                    else:
                        await delete_file(websocket, filename)
                    # Refresh file list
                    return await list_files(websocket)
            except (ValueError, IndexError):
                print_error("Invalid input for deletion. Format: Del <number>")
        else:
            try:
                file_index = int(key) - 1
                if 0 <= file_index < len(files):
                    # Check if locked
                    if file_status[file_index]["locked"]:
                        print_error(f"Cannot edit '{files[file_index]}' - file is locked by another user.")
                        await asyncio.sleep(1)
                        return await list_files(websocket)
                    else:
                        await edit_file(websocket, files[file_index])
                        return
                else:
                    print_error("Invalid file number.")
            except ValueError:
                print_error("Invalid input. Please enter a number.")

async def delete_file(websocket, filename):
    await websocket.send(json.dumps({"command": "DELETE_FILE", "filename": filename}))
    response = await websocket.recv()
    data = json.loads(response)
    
    if data.get("command") == "FILE_DELETED":
        print_success(f"File '{filename}' deleted successfully.")
    else:
        print_error(f"Failed to delete file: {data.get('message', 'Unknown error')}")
    
    await asyncio.sleep(1)

async def create_new_file(websocket):
    filename = input("Enter new filename: ")
    await websocket.send(json.dumps({"command": "CREATE_FILE", "filename": filename}))
    response = await websocket.recv()
    data = json.loads(response)
    if data.get("command") == "FILE_CREATED":
        print_success(f"File '{filename}' created successfully.")
        await edit_file(websocket, filename)
    else:
        print_error(f"Failed to create file: {data.get('message', 'Unknown error')}")
        await asyncio.sleep(1)

async def edit_file(websocket, filename):
    await websocket.send(json.dumps({"command": "OPEN", "filename": filename}))
    response = await websocket.recv()
    data = json.loads(response)
    
    if data.get("command") == "ERROR":
        print_error(data.get("message", "Unknown error"))
        await asyncio.sleep(2)
        return
        
    content = data.get("content", "")
    
    # Use curses for Vim-like editing
    def start_editor():
        return curses.wrapper(lambda stdscr: VimEditor(stdscr, content).run())
    
    # Run the editor in a separate thread to avoid blocking asyncio
    result = None
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(start_editor)
        result = future.result()
    
    # Handle the result from the editor
    if result == "run":
        await run_file(websocket, filename)
        await edit_file(websocket, filename)  # Return to editing after running
    elif result is not None:  # Save and quit
        await websocket.send(json.dumps({
            "command": "EDIT",
            "filename": filename,
            "content": result
        }))
        await websocket.send(json.dumps({"command": "CLOSE", "filename": filename}))

async def run_file(websocket, filename):
    # Clear the screen before running
    clear_screen()
    print_header(f"Running: {filename}")
    print("Program output:\n")
    
    # Start the program
    await websocket.send(json.dumps({"command": "RUN", "filename": filename}))
    
    # Set up input processing
    input_task = None
    program_running = True
    
    # Function to handle user input in a separate thread
    async def process_input():
        while program_running:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(None, input)
                await websocket.send(json.dumps({
                    "command": "PROGRAM_INPUT",
                    "input": user_input
                }))
            except (EOFError, KeyboardInterrupt):
                break
    
    try:
        # Start input processing
        input_task = asyncio.create_task(process_input())
        
        # Process program output
        while True:
            response = await websocket.recv()
            data = json.loads(response)
            
            if data["command"] == "OUTPUT":
                print(data["output"], end="")
                sys.stdout.flush()  # Ensure output is displayed immediately
                if data.get("finished", False):
                    break
            elif data["command"] == "PROGRAM_STARTED":
                print(f"{ANSI_BLUE}Program started...{ANSI_RESET}")
            elif data["command"] == "PROGRAM_FINISHED":
                print(f"\n{ANSI_GREEN}Program finished.{ANSI_RESET}")
                break
            elif data["command"] == "ERROR":
                print_error(data["message"])
                break
    finally:
        # Clean up
        program_running = False
        if input_task:
            input_task.cancel()
            try:
                await input_task
            except asyncio.CancelledError:
                pass
    
    input("\nPress Enter to continue...")

async def main():
    try:
        async with websockets.connect(SERVER_URI) as websocket:
            while await file_selection_screen(websocket):
                pass
    except ConnectionRefusedError:
        print_error("Could not connect to server. Make sure the server is running.")
    except Exception as e:
        print_error(f"An error occurred: {str(e)}")

# Add this import at the top
from concurrent.futures import ThreadPoolExecutor

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nClient stopped by user")