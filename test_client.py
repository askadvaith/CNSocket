import asyncio
import websockets
import json
import curses
import sys
import os
import platform
import traceback  # Added for better error reporting

# Configure server address - use localhost for working on the same system
SERVER_URI = "ws://localhost:8765"
filename = "script.py"  # Default filename
content = ""
output = ""
error_message = ""  # Added to store error messages
cursor_x = 0
cursor_y = 0
scroll_offset_y = 0  # Track vertical scroll position

# Check if we need to configure Windows terminal for proper curses support
if platform.system() == "Windows":
    # Ensure windows-curses package is installed
    try:
        import curses
    except ImportError:
        print("On Windows, you need to install windows-curses package:")
        print("pip install windows-curses")
        sys.exit(1)
    
    # Try to enable VT100 processing for better Windows terminal support
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except:
        pass

# Function to filter source code files
def is_source_file(filename):
    """Filter function to show only source code files (not executables)"""
    # Common source file extensions to include
    source_extensions = [
        '.py', '.c', '.cpp', '.h', '.hpp', '.java', '.js', '.html', '.css',
        '.php', '.rb', '.go', '.rs', '.ts', '.sh', '.bat', '.md', '.txt',
        '.json', '.xml', '.yaml', '.yml', '.ini', '.cfg', '.conf'
    ]
    
    # Check if the file has a source extension
    _, ext = os.path.splitext(filename.lower())
    return ext in source_extensions

async def file_selection_screen(stdscr, websocket):
    """Display a menu for file selection or creation"""
    global filename
    
    curses.curs_set(0)  # Hide cursor
    stdscr.clear()
    
    # Get list of existing files
    await websocket.send(json.dumps({"command": "LIST_FILES"}))
    
    # Wait for response
    response = await websocket.recv()
    data = json.loads(response)
    
    files = data.get("files", [])
    
    # Filter out executable files and other non-source files
    files = [f for f in files if is_source_file(f)]
    
    # Menu options
    options = files + ["[Create New File]"]
    selected = 0
    
    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()
        
        # Draw header
        stdscr.addstr(0, 0, "Select a file to edit or create a new one:")
        stdscr.addstr(1, 0, "Use arrow keys to navigate, Enter to select, Ctrl+X to exit")
        
        # Draw file options
        for i, option in enumerate(options):
            y = i + 3
            if y < height:
                if i == selected:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(y, 2, option[:width-4])
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(y, 2, option[:width-4])
        
        stdscr.refresh()
        
        # Handle input
        key = stdscr.getch()
        
        if key == curses.KEY_UP and selected > 0:
            selected -= 1
        elif key == curses.KEY_DOWN and selected < len(options) - 1:
            selected += 1
        elif key in (curses.KEY_ENTER, 10, 13):  # Enter key
            if selected == len(options) - 1:  # Create new file
                return await create_new_file(stdscr, websocket)
            else:
                filename = options[selected]
                return True
                
        elif key == 24:  # Ctrl+X key to exit
            return False  # Exit

async def create_new_file(stdscr, websocket):
    """Handle new file creation"""
    global filename
    
    curses.echo()  # Show user input
    stdscr.clear()
    
    # Draw prompt
    stdscr.addstr(0, 0, "Enter new filename (e.g., script.py, hello.c, Test.java):")
    stdscr.addstr(1, 0, "> ")
    stdscr.refresh()
    
    # Get filename input
    curses.curs_set(1)  # Show cursor
    stdscr.nodelay(False)  # Blocking input
    
    # Create a subwindow for text input
    input_win = curses.newwin(1, 50, 1, 2)
    input_win.refresh()
    
    # Get string input
    curses.echo()
    new_filename = input_win.getstr(0, 0, 49).decode('utf-8')
    curses.noecho()
    
    if not new_filename:
        return False
    
    # Send create file command to server
    await websocket.send(json.dumps({"command": "CREATE_FILE", "filename": new_filename}))
    
    # Wait for confirmation
    response = await websocket.recv()
    data = json.loads(response)
    
    if data.get("command") == "FILE_CREATED":
        filename = new_filename
        return True
    
    return False

# Function to adjust scroll position based on cursor
def adjust_scroll_position(cursor_y, editor_height):
    global scroll_offset_y
    
    # Keep cursor in view with some margin
    margin = min(3, editor_height // 4)
    
    # If cursor is above visible area, scroll up
    if cursor_y < scroll_offset_y + margin:
        scroll_offset_y = max(0, cursor_y - margin)
    
    # If cursor is below visible area, scroll down
    elif cursor_y >= scroll_offset_y + editor_height - margin:
        scroll_offset_y = max(0, cursor_y - editor_height + margin + 1)

async def update_screen(stdscr, websocket, cursor_pos=None):
    global content, output, error_message, cursor_x, cursor_y, scroll_offset_y
    
    # Configure curses
    curses.curs_set(1)  # Show cursor
    curses.use_default_colors()  # Use terminal default colors
    
    # Initial screen
    stdscr.clear()
    height, width = stdscr.getmaxyx()
    header = f"Editing: {filename} (Press 'Ctrl+X' to exit, 'Ctrl+R' to run)"
    stdscr.addstr(0, 0, header[:width-1])
    stdscr.refresh()
    
    editor_start_y = 2
    output_start_y = height // 2
    
    # Calculate editor height
    editor_height = output_start_y - editor_start_y - 1
    
    # Fix: Draw the editor once initially to make sure content is displayed
    draw_editor(stdscr, height, width, editor_start_y, output_start_y)
    
    # Adjust scroll position for initial cursor
    adjust_scroll_position(cursor_y, editor_height)
    
    # Position cursor correctly
    try:
        stdscr.move(editor_start_y + cursor_y - scroll_offset_y, cursor_x)
    except curses.error:
        # Ignore cursor positioning errors
        pass
        
    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.recv(), timeout=0.1)
                data = json.loads(message)

                if data["command"] == "LOAD":
                    content = data["content"]
                elif data["command"] == "UPDATE":
                    content = data["content"]
                elif data["command"] == "OUTPUT":
                    output = data["output"]
                elif data["command"] == "ERROR":  # Handle server errors
                    error_message = data["message"]
                    output += f"\nERROR: {error_message}\n"
                
                # Recalculate editor height
                editor_height = output_start_y - editor_start_y - 1
                
                # Adjust scroll position
                adjust_scroll_position(cursor_y, editor_height)
                
                # Redraw entire screen
                draw_editor(stdscr, height, width, editor_start_y, output_start_y)
                
                # Restore cursor position with scroll offset
                try:
                    stdscr.move(editor_start_y + cursor_y - scroll_offset_y, cursor_x)
                except curses.error:
                    # Ignore cursor positioning errors
                    pass
                
            except asyncio.TimeoutError:
                # Regular timeout, just continue and check for input
                pass
            except websockets.exceptions.ConnectionClosed:
                stdscr.addstr(height-1, 0, "Connection closed. Press any key to exit.")
                stdscr.refresh()
                stdscr.getch()
                break
            except Exception as e:
                # Handle other exceptions - FIX: Make errors more visible
                error_message = f"Error: {str(e)}\n{traceback.format_exc()}"
                output = error_message  # Display in the output area
                draw_editor(stdscr, height, width, editor_start_y, output_start_y)
                
                # Makes sure error is visible for at least 3 seconds
                stdscr.nodelay(False)  # Switch to blocking mode temporarily
                stdscr.getch()  # Wait for keypress
                stdscr.nodelay(True)  # Back to non-blocking
                
            # Refresh the screen - but not too frequently to avoid flicker
            # We'll only redraw every 200ms to reduce CPU usage and flickering
            draw_editor(stdscr, height, width, editor_start_y, output_start_y)
            
            # Update cursor position with scroll offset
            try:
                stdscr.move(editor_start_y + cursor_y - scroll_offset_y, cursor_x)
            except curses.error:
                # Ignore curses errors when moving cursor
                pass
                
            await asyncio.sleep(0.2)  # Reduced refresh rate
    except Exception as e:
        error_message = f"Fatal error: {str(e)}\n{traceback.format_exc()}"
        stdscr.clear()
        stdscr.addstr(0, 0, error_message[:height-1])
        stdscr.refresh()
        stdscr.nodelay(False)  # Switch to blocking mode
        stdscr.getch()  # Wait for keypress before continuing

def draw_editor(stdscr, height, width, editor_start_y, output_start_y):
    global error_message, cursor_x, cursor_y, scroll_offset_y, content
    
    # Clear screen
    stdscr.clear()
    
    # Draw header
    header = f"Editing: {filename} (Press 'Ctrl+X' to exit, 'Ctrl+R' to run)"
    stdscr.addstr(0, 0, header[:width-1])
    
    # Calculate available editor space
    editor_height = output_start_y - editor_start_y - 1
    
    # Draw separator
    separator = "-" * (width - 1)
    stdscr.addstr(editor_start_y - 1, 0, separator)
    stdscr.addstr(output_start_y - 1, 0, separator)
    stdscr.addstr(output_start_y - 1, 0, " OUTPUT ")
    
    # Show scroll indicators if needed
    content_lines = content.split('\n')
    if scroll_offset_y > 0:
        stdscr.addstr(editor_start_y, width - 3, "↑")
    if len(content_lines) > scroll_offset_y + editor_height:
        stdscr.addstr(output_start_y - 2, width - 3, "↓")
    
    # Draw content (code editor) with scroll offset
    for i in range(min(editor_height, len(content_lines) - scroll_offset_y)):
        y_pos = editor_start_y + i
        content_line_idx = scroll_offset_y + i
        
        if content_line_idx < len(content_lines):
            line = content_lines[content_line_idx]
            try:
                # Display content at the original position, no offset for line numbers
                stdscr.addstr(y_pos, 0, line[:width-1])
            except curses.error:
                # Ignore curses errors when writing at the edge of the screen
                pass
    
    # Display any error message first in the output area
    if error_message:
        try:
            stdscr.attron(curses.A_BOLD)  # Make error messages bold
            stdscr.addstr(output_start_y, 0, "ERROR: ")
            stdscr.attroff(curses.A_BOLD)
            
            # Display error message, split into multiple lines if needed
            err_lines = error_message.split('\n')
            for i, line in enumerate(err_lines):
                if output_start_y + i + 1 < height - 1:
                    stdscr.addstr(output_start_y + i + 1, 0, line[:width-1])
        except curses.error:
            # Ignore curses errors when writing at the edge of the screen
            pass
    
    # Draw output below any error message
    output_lines = output.split('\n')
    start_line = 2 if error_message else 0  # Skip a couple lines if there's an error
    for i, line in enumerate(output_lines):
        if output_start_y + i + start_line < height - 1:
            try:
                stdscr.addstr(output_start_y + i + start_line, 0, line[:width-1])
            except curses.error:
                # Ignore curses errors when writing at the edge of the screen
                pass
    
    # Show cursor position at bottom of screen
    pos_info = f"Line: {cursor_y+1}/{len(content_lines)}"
    try:
        stdscr.addstr(height-1, width - len(pos_info) - 1, pos_info)
    except curses.error:
        # Ignore positioning errors
        pass
    
    stdscr.refresh()

async def send_edits(websocket, stdscr):
    global content, output, error_message, cursor_x, cursor_y, scroll_offset_y
    
    # Set up non-blocking input
    stdscr.nodelay(True)
    
    content_lines = content.split('\n')
    editor_start_y = 2
    
    try:
        while True:
            try:
                key = stdscr.getch()
                
                # No key pressed
                if key == -1:
                    await asyncio.sleep(0.01)
                    continue
                
                # Get current screen dimensions
                height, width = stdscr.getmaxyx()
                output_start_y = height // 2
                editor_height = output_start_y - editor_start_y - 1
                
                # Get latest content lines
                content_lines = content.split('\n')
                
                # Ctrl+X key to exit (ASCII value 24)
                if key == 24:
                    # Send CLOSE command to server
                    await websocket.send(json.dumps({"command": "CLOSE", "filename": filename}))
                    # Clear editor state
                    content = ""
                    output = ""
                    error_message = ""
                    scroll_offset_y = 0  # Reset scroll position
                    # Cancel the tasks to exit edit mode
                    edit_task.cancel()
                    update_task.cancel()
                    return
                    
                # Run code with Ctrl+R
                elif key == 18:  # ASCII code for Ctrl+R
                    await websocket.send(json.dumps({"command": "RUN", "filename": filename}))
                    
                # Page Up/Down for scrolling
                elif key == curses.KEY_PPAGE:  # Page Up
                    scroll_offset_y = max(0, scroll_offset_y - editor_height + 2)
                    # Move cursor up if needed
                    if cursor_y > scroll_offset_y + editor_height - 1:
                        cursor_y = scroll_offset_y + editor_height - 1
                elif key == curses.KEY_NPAGE:  # Page Down
                    max_scroll = max(0, len(content_lines) - editor_height)
                    scroll_offset_y = min(max_scroll, scroll_offset_y + editor_height - 2)
                    # Move cursor down if needed
                    if cursor_y < scroll_offset_y:
                        cursor_y = scroll_offset_y
                
                # Backspace (different codes for different platforms)
                elif key in [curses.KEY_BACKSPACE, 127, 8]:
                    # Make sure cursor is within valid range
                    if cursor_y >= len(content_lines):
                        cursor_y = len(content_lines) - 1
                    
                    if cursor_x > 0:
                        # Remove character within line
                        current_line = content_lines[cursor_y]
                        content_lines[cursor_y] = current_line[:cursor_x-1] + current_line[cursor_x:]
                        cursor_x -= 1
                    elif cursor_y > 0:
                        # Join with previous line
                        prev_line = content_lines[cursor_y-1]
                        cursor_x = len(prev_line)
                        content_lines[cursor_y-1] = prev_line + content_lines[cursor_y]
                        content_lines.pop(cursor_y)
                        cursor_y -= 1
                        
                # Enter key
                elif key in (curses.KEY_ENTER, 10, 13):
                    # Make sure cursor is within valid range
                    if cursor_y >= len(content_lines):
                        cursor_y = len(content_lines) - 1
                    
                    current_line = content_lines[cursor_y]
                    content_lines[cursor_y] = current_line[:cursor_x]
                    content_lines.insert(cursor_y + 1, current_line[cursor_x:])
                    cursor_y += 1
                    cursor_x = 0
                    
                # Arrow keys for navigation
                elif key == curses.KEY_LEFT and cursor_x > 0:
                    cursor_x -= 1
                elif key == curses.KEY_RIGHT:
                    if cursor_y < len(content_lines) and cursor_x < len(content_lines[cursor_y]):
                        cursor_x += 1
                elif key == curses.KEY_UP and cursor_y > 0:
                    cursor_y -= 1
                    cursor_x = min(cursor_x, len(content_lines[cursor_y]))
                elif key == curses.KEY_DOWN:
                    if cursor_y < len(content_lines) - 1:
                        cursor_y += 1
                        cursor_x = min(cursor_x, len(content_lines[cursor_y]))
                # Home key - move to start of line
                elif key == curses.KEY_HOME:
                    cursor_x = 0
                # End key - move to end of line
                elif key == curses.KEY_END:
                    if cursor_y < len(content_lines):
                        cursor_x = len(content_lines[cursor_y])
                    
                # Regular character
                elif key < 256:
                    # Make sure cursor is within valid range
                    if cursor_y >= len(content_lines):
                        cursor_y = len(content_lines) - 1
                    
                    current_line = content_lines[cursor_y]
                    content_lines[cursor_y] = current_line[:cursor_x] + chr(key) + current_line[cursor_x:]
                    cursor_x += 1
                
                # Update content
                content = '\n'.join(content_lines)
                await websocket.send(json.dumps({"command": "EDIT", "filename": filename, "content": content}))
                
                # Adjust scroll position to keep cursor visible
                adjust_scroll_position(cursor_y, editor_height)
                
                # Place cursor at the right position with scroll offset - NO OFFSET NOW
                try:
                    stdscr.move(editor_start_y + cursor_y - scroll_offset_y, cursor_x)
                except curses.error:
                    # Ignore curses errors when moving cursor
                    pass
                    
                # Clear any previous error
                error_message = ""
                
                # Update screen with new cursor position
                draw_editor(stdscr, height, width, editor_start_y, output_start_y)
                
                # Place cursor again after redraw - NO OFFSET NOW
                try:
                    stdscr.move(editor_start_y + cursor_y - scroll_offset_y, cursor_x)
                except curses.error:
                    # Ignore curses errors when moving cursor
                    pass
                    
            except websockets.exceptions.ConnectionClosed:
                break
            except Exception as e:
                error_message = f"Error: {str(e)}\n{traceback.format_exc()}"
                height, width = stdscr.getmaxyx()
                output_start_y = height // 2
                draw_editor(stdscr, height, width, editor_start_y, output_start_y)
                
                # Make sure error is visible
                stdscr.nodelay(False)  # Switch to blocking mode temporarily
                stdscr.getch()  # Wait for keypress
                stdscr.nodelay(True)  # Back to non-blocking
                
    except Exception as e:
        # Show error and wait for a key press
        error_message = f"Fatal error in edit loop: {str(e)}\n{traceback.format_exc()}"
        height, width = stdscr.getmaxyx()
        stdscr.clear()
        stdscr.addstr(0, 0, error_message[:height-1])
        stdscr.refresh()
        stdscr.nodelay(False)  # Switch back to blocking input
        stdscr.getch()

async def main(stdscr):
    global error_message, filename, content, output, scroll_offset_y
    
    # Initialize screen
    curses.start_color()
    curses.curs_set(1)
    stdscr.clear()
    stdscr.addstr(0, 0, f"Connecting to {SERVER_URI}...")
    stdscr.refresh()
    
    try:
        async with websockets.connect(SERVER_URI) as websocket:
            stdscr.clear()
            stdscr.addstr(0, 0, "Connected!")
            stdscr.refresh()
            
            while True:  # Add a loop to return to file selection after exiting edit mode
                # Reset scroll position for new file
                scroll_offset_y = 0
                
                # Display file selection screen
                file_selected = await file_selection_screen(stdscr, websocket)
                if not file_selected:
                    return
                
                # Now open the selected file
                await websocket.send(json.dumps({"command": "OPEN", "filename": filename}))
                
                # Wait for the server to respond with the file content
                response = await websocket.recv()
                try:
                    data = json.loads(response)
                    if data["command"] == "LOAD":
                        content = data["content"]
                except Exception as e:
                    error_message = f"Error loading file: {str(e)}"
                

                # Create a variable to share between tasks
                edit_done = False
                
                # Make tasks accessible in the key handler
                global edit_task, update_task

                # Create separate tasks for screen updates and user input
                edit_task = asyncio.create_task(send_edits(websocket, stdscr))
                update_task = asyncio.create_task(update_screen(stdscr, websocket))
                
                try:
                    # Wait for both tasks
                    await asyncio.gather(edit_task, update_task)
                except asyncio.CancelledError:
                    pass
                finally:
                    # Ensure tasks are properly cancelled
                    if not edit_task.done():
                        edit_task.cancel()
                    if not update_task.done():
                        update_task.cancel()
                    
                    # Try to await cancelled tasks to handle any exceptions
                    try:
                        await edit_task
                    except asyncio.CancelledError:
                        pass
                    
                    try:
                        await update_task
                    except asyncio.CancelledError:
                        pass
                
                # If we reach here normally (not through return from file_selection_screen),
                # we continue the loop to return to file selection
                
    except websockets.exceptions.ConnectionError:
        stdscr.clear()
        stdscr.addstr(0, 0, f"Could not connect to server at {SERVER_URI}")
        stdscr.addstr(1, 0, "Make sure the server is running. Press any key to exit.")
        stdscr.refresh()
        stdscr.getch()
    except Exception as e:
        error_message = f"Error: {str(e)}\n{traceback.format_exc()}"
        stdscr.clear()
        stdscr.addstr(0, 0, error_message[:curses.LINES-2])
        stdscr.addstr(curses.LINES-1, 0, "Press any key to exit.")
        stdscr.refresh()
        stdscr.getch()
        
def run_client():
    if platform.system() == "Windows":
        # For Windows, we need special handling
        try:
            curses.wrapper(lambda stdscr: asyncio.run(main(stdscr)))
        except Exception as e:
            print(f"Fatal error: {str(e)}")
            print(traceback.format_exc())
    else:
        # For Unix/Linux/Mac
        try:
            curses.wrapper(lambda stdscr: asyncio.run(main(stdscr)))
        except Exception as e:
            print(f"Fatal error: {str(e)}")
            print(traceback.format_exc())

if __name__ == "__main__":
    run_client()