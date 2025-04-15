#!/usr/bin/env python3
import asyncio
import websockets
import json
import os
import sys
import curses
from enum import Enum

class Mode(Enum):
    NORMAL = 1
    INSERT = 2

class TextEditor:
    def __init__(self, content="", filename=""):
        self.content = content.split('\n')
        self.filename = filename
        self.mode = Mode.NORMAL
        self.cursor_x = 0
        self.cursor_y = 0
        self.top_line = 0
        self.message = ""
        self.command_buffer = ""
        self.modified = False
        
    def run(self, stdscr):
        """Main editor loop using curses"""
        # Setup
        curses.curs_set(1)  # Show cursor
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLUE)  # Status line
        curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Command line
        curses.init_pair(3, curses.COLOR_GREEN, -1)  # Message
        
        # Ensure content is not empty
        if not self.content:
            self.content = [""]
            
        # Main loop
        running = True
        while running:
            stdscr.clear()
            height, width = stdscr.getmaxyx()
            
            # Display content
            display_height = height - 2  # Reserve space for status bar and message
            for i in range(display_height):
                line_num = i + self.top_line
                if line_num < len(self.content):
                    line = self.content[line_num]
                    if len(line) > width - 1:
                        line = line[:width - 1]
                    stdscr.addstr(i, 0, line)
                    
            # Status line
            status = f" {self.filename} "
            status += f"{'[+]' if self.modified else ''}".ljust(10)
            mode_str = f" {self.mode.name} MODE "
            cursor_pos = f" Ln {self.cursor_y + 1}, Col {self.cursor_x + 1} "
            
            remaining = width - len(status) - len(mode_str) - len(cursor_pos)
            if remaining > 0:
                status += " " * remaining
                
            stdscr.attron(curses.color_pair(1))
            stdscr.addstr(height - 2, 0, status)
            stdscr.addstr(height - 2, len(status) - len(mode_str) - len(cursor_pos), mode_str)
            stdscr.addstr(height - 2, width - len(cursor_pos), cursor_pos)
            stdscr.attroff(curses.color_pair(1))
            
            # Message line
            if self.message:
                stdscr.attron(curses.color_pair(3))
                stdscr.addstr(height - 1, 0, self.message[:width-1])
                stdscr.attroff(curses.color_pair(3))
                
            # Command line
            if self.mode == Mode.NORMAL and self.command_buffer:
                stdscr.attron(curses.color_pair(2))
                stdscr.addstr(height - 1, 0, ":" + self.command_buffer)
                stdscr.attroff(curses.color_pair(2))
                
            # Position cursor
            cursor_screen_y = self.cursor_y - self.top_line
            if 0 <= cursor_screen_y < display_height:
                current_line = self.content[self.cursor_y]
                cursor_x = min(self.cursor_x, len(current_line))
                stdscr.move(cursor_screen_y, cursor_x)
                
            # Process key
            key = stdscr.getch()
            running = self.process_key(key, height, width)
            
            # Clear message after any key press
            self.message = ""
            
        return self.content, self.modified
        
    def process_key(self, key, height, width):
        """Process a keypress"""
        display_height = height - 2  # Adjust for status and message lines
        
        if self.mode == Mode.NORMAL:
            return self._process_normal_mode(key, display_height)
        elif self.mode == Mode.INSERT:
            return self._process_insert_mode(key, display_height)
            
        return True
        
    def _process_normal_mode(self, key, display_height):
        """Process keys in normal mode"""
        # Handle command input
        if self.command_buffer:
            if key == ord('\n'):  # Enter to execute command
                command = self.command_buffer.strip()
                self.command_buffer = ""
                return self._execute_command(command)
            elif key == 27:  # ESC to cancel
                self.command_buffer = ""
                return True
            elif key in (curses.KEY_BACKSPACE, 127, 8):  # Backspace
                self.command_buffer = self.command_buffer[:-1]
                return True
            else:
                char = chr(key) if 32 <= key <= 126 else ""
                if char:
                    self.command_buffer += char
                return True
                
        # Normal mode shortcuts
        if key == ord('i'):  # Enter insert mode
            self.mode = Mode.INSERT
        elif key == ord(':'):  # Command mode
            self.command_buffer = ""
        elif key == ord('q'):  # Quick exit shortcut
            return False
        elif key == ord('h') or key == curses.KEY_LEFT:
            self._move_cursor_left()
        elif key == ord('j') or key == curses.KEY_DOWN:
            self._move_cursor_down()
        elif key == ord('k') or key == curses.KEY_UP:
            self._move_cursor_up()
        elif key == ord('l') or key == curses.KEY_RIGHT:
            self._move_cursor_right()
        elif key == ord('r'):  # Run file shortcut
            self.command_buffer = "run"
            return self._execute_command("run")
            
        return True
        
    def _process_insert_mode(self, key, display_height):
        """Process keys in insert mode"""
        if key == 27:  # ESC to exit insert mode
            self.mode = Mode.NORMAL
            # Adjust cursor if at end of line
            if self.cursor_y < len(self.content) and self.cursor_x > 0 and self.cursor_x >= len(self.content[self.cursor_y]):
                self.cursor_x = max(0, len(self.content[self.cursor_y]) - 1)
        elif key == curses.KEY_LEFT:
            self._move_cursor_left()
        elif key == curses.KEY_DOWN:
            self._move_cursor_down()
        elif key == curses.KEY_UP:
            self._move_cursor_up()
        elif key == curses.KEY_RIGHT:
            self._move_cursor_right()
        elif key == curses.KEY_BACKSPACE or key == 127:
            if self.cursor_x > 0:
                current_line = self.content[self.cursor_y]
                self.content[self.cursor_y] = current_line[:self.cursor_x-1] + current_line[self.cursor_x:]
                self.cursor_x -= 1
                self.modified = True
            elif self.cursor_y > 0:  # Backspace at start of line
                prev_line = self.content[self.cursor_y-1]
                current_line = self.content[self.cursor_y]
                self.cursor_x = len(prev_line)
                self.content[self.cursor_y-1] = prev_line + current_line
                self.content.pop(self.cursor_y)
                self.cursor_y -= 1
                self.modified = True
        elif key == 10 or key == 13:  # Enter
            current_line = self.content[self.cursor_y]
            self.content[self.cursor_y] = current_line[:self.cursor_x]
            self.content.insert(self.cursor_y + 1, current_line[self.cursor_x:])
            self.cursor_y += 1
            self.cursor_x = 0
            self._ensure_visible(self.cursor_y, display_height)
            self.modified = True
        elif 32 <= key <= 126:  # Printable ASCII
            char = chr(key)
            current_line = self.content[self.cursor_y]
            self.content[self.cursor_y] = current_line[:self.cursor_x] + char + current_line[self.cursor_x:]
            self.cursor_x += 1
            self.modified = True
            
        return True
        
    def _move_cursor_up(self):
        """Move cursor up"""
        if self.cursor_y > 0:
            self.cursor_y -= 1
            # Adjust x position if line is shorter
            if self.cursor_y < len(self.content):
                self.cursor_x = min(self.cursor_x, len(self.content[self.cursor_y]))
                
            # Scroll if needed
            if self.cursor_y < self.top_line:
                self.top_line = self.cursor_y
                
    def _move_cursor_down(self):
        """Move cursor down"""
        if self.cursor_y < len(self.content) - 1:
            self.cursor_y += 1
            # Adjust x position if line is shorter
            if self.cursor_y < len(self.content):
                self.cursor_x = min(self.cursor_x, len(self.content[self.cursor_y]))
                
            # Scroll if needed
            self._ensure_visible(self.cursor_y, None)
                
    def _move_cursor_left(self):
        """Move cursor left"""
        if self.cursor_x > 0:
            self.cursor_x -= 1
            
    def _move_cursor_right(self):
        """Move cursor right"""
        if self.cursor_y < len(self.content) and self.cursor_x < len(self.content[self.cursor_y]):
            self.cursor_x += 1
            
    def _ensure_visible(self, line, display_height):
        """Ensure a line is visible by scrolling if needed"""
        if display_height is None:
            # Estimate display height if not provided
            display_height = 20
            
        if line >= self.top_line + display_height:
            self.top_line = line - display_height + 1
        elif line < self.top_line:
            self.top_line = line
            
    def _execute_command(self, command):
        """Execute a command in normal mode"""
        if command == "q":  # Quit
            if self.modified:
                self.message = "File has unsaved changes. Use :q! to force quit."
                return True
            return False
        elif command == "q!":  # Force quit
            return False
        elif command == "w":  # Save
            self.modified = False
            self.message = f"File saved: {self.filename}"
            return True
        elif command == "wq":  # Save and quit
            self.modified = False
            return False
        elif command == "run":  # Run file
            self.message = "Running file..."
            # We'll return True here, but set a flag for the client to run the file
            return "run"
            
        self.message = f"Unknown command: {command}"
        return True

class CodeClient:
    def __init__(self, server_uri="ws://localhost:8765"):
        self.server_uri = server_uri
        self.websocket = None
        self.running = True
        
    async def connect(self):
        """Connect to the WebSocket server"""
        try:
            self.websocket = await websockets.connect(self.server_uri)
            return True
        except Exception as e:
            print(f"Error connecting to server: {str(e)}")
            return False
            
    async def close(self):
        """Close the WebSocket connection"""
        if self.websocket:
            await self.websocket.close()
            
    async def list_files(self):
        """Get list of files from server"""
        await self.websocket.send(json.dumps({
            "action": "list_files"
        }))
        
        response = await self.websocket.recv()
        return json.loads(response)
        
    async def get_file(self, filename):
        """Get file content from server"""
        await self.websocket.send(json.dumps({
            "action": "get_file",
            "filename": filename
        }))
        
        response = await self.websocket.recv()
        return json.loads(response)
        
    async def save_file(self, filename, content):
        """Save file content to server"""
        await self.websocket.send(json.dumps({
            "action": "save_file",
            "filename": filename,
            "content": content
        }))
        
        response = await self.websocket.recv()
        return json.loads(response)
        
    async def create_file(self, filename, file_type):
        """Create a new file on the server"""
        await self.websocket.send(json.dumps({
            "action": "create_file",
            "filename": filename,
            "type": file_type
        }))
        
        response = await self.websocket.recv()
        return json.loads(response)
        
    async def run_file(self, filename, input_data=""):
        """Run a file on the server"""
        await self.websocket.send(json.dumps({
            "action": "run_file",
            "filename": filename,
            "input": input_data
        }))
        
        response = await self.websocket.recv()
        return json.loads(response)
        
    async def main_menu(self):
        """Display the main menu and handle user input"""
        while self.running:
            # Clear screen
            os.system('cls' if os.name == 'nt' else 'clear')
            
            # Get file list
            files_response = await self.list_files()
            
            if files_response["status"] != "success":
                print(f"Error: {files_response.get('message', 'Unknown error')}")
                input("Press Enter to continue...")
                continue
                
            # Display menu
            print("===== CODE EDITOR =====")
            print("Files:")
            
            files = files_response.get("files", [])
            if not files:
                print("  No files found")
            else:
                for i, file in enumerate(files, 1):
                    print(f"  {i}. {file}")
                    
            print("\nOptions:")
            print("  n. Create new file")
            print("  q. Quit")
            print("=====================")
            
            choice = input("Select an option: ").strip().lower()
            
            if choice == 'q':
                self.running = False
            elif choice == 'n':
                await self.create_new_file()
            elif choice.isdigit() and 1 <= int(choice) <= len(files):
                filename = files[int(choice) - 1]
                await self.edit_file(filename)
                
    async def create_new_file(self):
        """Create a new file"""
        os.system('cls' if os.name == 'nt' else 'clear')
        print("===== CREATE NEW FILE =====")
        
        filename = input("Enter filename (without extension): ").strip()
        if not filename:
            print("Filename cannot be empty")
            input("Press Enter to continue...")
            return
            
        print("\nSelect file type:")
        print("  1. Python (.py)")
        print("  2. C (.c)")
        
        type_choice = input("Select file type (1-2): ").strip()
        
        file_type = "py"
        if type_choice == "2":
            file_type = "c"
            
        response = await self.create_file(filename, file_type)
        
        if response["status"] == "success":
            print(f"\nFile created: {response.get('filename')}")
            input("Press Enter to edit the file...")
            await self.edit_file(response.get('filename'))
        else:
            print(f"\nError: {response.get('message', 'Unknown error')}")
            input("Press Enter to continue...")
            
    async def edit_file(self, filename):
        """Open and edit a file"""
        # Get file content
        response = await self.get_file(filename)
        
        if response["status"] != "success":
            print(f"Error: {response.get('message', 'Unknown error')}")
            input("Press Enter to continue...")
            return
            
        content = response.get("content", "")
        
        # Edit file using the editor
        editor = TextEditor(content, filename)
        result = curses.wrapper(editor.run)
        
        run_after_edit = False

        if isinstance(result, tuple):
            # Either (content_lines, modified) or ("run", modified)
            if result[0] == "run":
                run_after_edit = True
                content_lines, modified = result[1:]
            else:
                content_lines, modified = result

            if modified:
                content_text = "\n".join(content_lines)
                save_response = await self.save_file(filename, content_text)
                if save_response["status"] == "success":
                    print(f"File saved: {filename}")
                else:
                    print(f"Error saving file: {save_response.get('message', 'Unknown error')}")

            if run_after_edit:
                await self.execute_file(filename)
                
    async def execute_file(self, filename):
        """Run a file and show output"""
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"===== RUNNING {filename} =====")
        
        # Ask for input if needed
        print("Enter input for the program (press Ctrl+D or Ctrl+Z followed by Enter when done):")
        input_lines = []
        try:
            while True:
                line = input()
                input_lines.append(line)
        except EOFError:
            pass
        
        input_data = "\n".join(input_lines)
        
        # Run the file
        response = await self.run_file(filename, input_data)
        
        print("\n===== OUTPUT =====")
        if response["status"] == "success":
            if response.get("result"):
                print(response["result"], end="")
            if response.get("error"):
                print("STDERR:", response["error"], end="")
            print(f"\nExit code: {response.get('exit_code', 0)}")
        else:
            print(f"Error: {response.get('message', 'Unknown error')}")
            
        input("\nPress Enter to continue...")

async def main():
    client = CodeClient()
    
    print("Connecting to server...")
    connected = await client.connect()
    
    if not connected:
        print("Failed to connect to server. Make sure the server is running.")
        return
        
    try:
        await client.main_menu()
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        await client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)