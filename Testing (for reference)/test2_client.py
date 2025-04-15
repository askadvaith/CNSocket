import asyncio
import websockets
import json
import curses
import sys
import os
import platform
import traceback

# Configure server address
SERVER_URI = "ws://localhost:8765"
filename = "script.py"  # Default filename
content = ""
output = ""
error_message = ""
cursor_x = 0
cursor_y = 0
scroll_offset_y = 0  # Track vertical scroll position
input_mode = False   # Flag to track if we're in input mode

# Check if we need to configure Windows terminal
if platform.system() == "Windows":
    try:
        import curses
    except ImportError:
        print("On Windows, you need to install windows-curses package:")
        print("pip install windows-curses")
        sys.exit(1)
    
    # Try to enable VT100 processing for better Windows support
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except:
        pass

# Function to filter source code files
def is_source_file(filename):
    """Filter function to show only source code files (not executables)"""
    source_extensions = [
        '.py', '.c', '.cpp', '.h', '.hpp', '.java', '.js', '.html', '.css',
        '.php', '.rb', '.go', '.rs', '.ts', '.sh', '.bat', '.md', '.txt',
        '.json', '.xml', '.yaml', '.yml', '.ini', '.cfg', '.conf'
    ]
    
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
    file_status = data.get("file_status", [])
    
    # Convert file_status to dict for easier lookup
    locked_files = {}
    if file_status:
        for fs in file_status:
            locked_files[fs["name"]] = fs.get("locked", False)
    
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
        stdscr.addstr(1, 0, "Use arrow keys to navigate, Enter to select, Delete to remove file, Ctrl+X to exit")
        
        # Draw file options
        for i, option in enumerate(options):
            y = i + 3
            if y < height:
                if i == selected:
                    stdscr.attron(curses.A_REVERSE)
                    
                # Check if it's a real file (not the "Create" option) and it's locked
                if i < len(files) and locked_files.get(option, False):
                    stdscr.addstr(y, 2, f"{option} [LOCKED]"[:width-4])
                else:
                    stdscr.addstr(y, 2, option[:width-4])
                    
                if i == selected:
                    stdscr.attroff(curses.A_REVERSE)
        
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
                selected_file = options[selected]
                # Check if file is locked
                if locked_files.get(selected_file, False):
                    # Show "file is locked" message
                    stdscr.attron(curses.A_BOLD)
                    stdscr.addstr(height-2, 0, f"File '{selected_file}' is being edited by another user")
                    stdscr.attroff(curses.A_BOLD)
                    stdscr.refresh()
                    stdscr.nodelay(False)
                    stdscr.getch()  # Wait for keypress
                    stdscr.nodelay(True)
                else:
                    filename = selected_file
                    return True
        elif key == curses.KEY_DC and selected < len(files):  # Delete key
            file_to_delete = options[selected]
            
            # Check if file is locked
            if locked_files.get(file_to_delete, False):
                stdscr.attron(curses.A_BOLD)
                stdscr.addstr(height-2, 0, f"Cannot delete '{file_to_delete}' - it's being edited by another user")
                stdscr.attroff(curses.A_BOLD)
                stdscr.refresh()
                stdscr.nodelay(False)
                stdscr.getch()  # Wait for keypress
                stdscr.nodelay(True)
            else:
                # Confirm deletion
                stdscr.addstr(height-3, 0, f"Delete '{file_to_delete}'? (y/n): ")
                stdscr.refresh()
                stdscr.nodelay(False)  # Wait for keypress
                confirm = stdscr.getch()
                stdscr.nodelay(True)
                
                if confirm in (ord('y'), ord('Y')):
                    # Send delete command to server
                    await websocket.send(json.dumps({
                        "command": "DELETE_FILE", 
                        "filename": file_to_delete
                    }))
                    
                    # Wait for response
                    delete_response = await websocket.recv()
                    delete_data = json.loads(delete_response)
                    
                    if delete_data.get("command") == "FILE_DELETED":
                        # Refresh file list
                        await websocket.send(json.dumps({"command": "LIST_FILES"}))
                        response = await websocket.recv()
                        data = json.loads(response)
                        files = data.get("files", [])
                        file_status = data.get("file_status", [])
                        
                        # Update locked files dict
                        locked_files = {}
                        if file_status:
                            for fs in file_status:
                                locked_files[fs["name"]] = fs.get("locked", False)
                        
                        # Filter files again
                        files = [f for f in files if is_source_file(f)]
                        options = files + ["[Create New File]"]
                        if selected >= len(options):
                            selected = len(options) - 1
                    else:
                        # Show error message
                        error_msg = delete_data.get("message", "Unknown error")
                        stdscr.addstr(height-2, 0, f"Error: {error_msg}")
                        stdscr.refresh()
                        stdscr.nodelay(False)
                        stdscr.getch()  # Wait for keypress
                        stdscr.nodelay(True)
                
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

async def handle_program_input(stdscr, websocket, input_queue):
    """Handle input when running programs"""
    global input_mode
    
    height, width = stdscr.getmaxyx()
    
    # Create input area at the bottom of the screen
    input_area = curses.newwin(1, width - 2, height - 2, 0)
    input_area.keypad(True)
    
    stdscr.addstr(height - 3, 0, "Program Input Mode (Enter to submit, Esc to exit): ")
    stdscr.refresh()
    
    # Configure input settings - FIXED: removed echo() to prevent "text must be False" error
    curses.curs_set(1)  # Show cursor
    
    input_str = ""
    
    while input_mode:
        input_area.clear()
        input_area.addstr(0, 0, "> " + input_str)
        input_area.refresh()
        
        try:
            # Get key input non-blocking
            key = input_area.getch()
            
            if key == 27:  # Escape key
                input_mode = False
                break
            elif key in (10, 13):  # Enter key
                # Send input to program
                await input_queue.put(input_str + "\n")
                
                # Send input to server
                await websocket.send(json.dumps({
                    "command": "PROGRAM_INPUT",
                    "input": input_str + "\n"
                }))
                
                input_str = ""
            elif key == curses.KEY_BACKSPACE or key == 8 or key == 127:
                if input_str:
                    input_str = input_str[:-1]
            elif 32 <= key <= 126:  # Printable characters
                input_str += chr(key)
        except Exception as e:
            error_message = f"Input error: {str(e)}"
            break
    
    # Restore settings
    curses.noecho()
    curses.curs_set(0)

def draw_editor(stdscr, height, width, editor_start_y, output_start_y):
    global error_message, cursor_x, cursor_y, scroll_offset_y, content, input_mode
    
    # Clear screen
    stdscr.clear()
    
    # Draw header
    header_text = f"Editing: {filename} (Press 'Ctrl+X' to exit, 'Ctrl+R' to run)"
    if not input_mode:
        header_text += ", 'Ctrl+I' for program input"
    stdscr.addstr(0, 0, header_text[:width-1])
    
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
                # Display line numbers
                stdscr.addstr(y_pos, 0, f"{content_line_idx+1:4} | ")
                # Display content after line numbers
                stdscr.addstr(y_pos, 7, line[:width-8])
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
    
    # Show input prompt if in input mode
    if input_mode:
        try:
            stdscr.addstr(height - 3, 0, "Program Input Mode (Enter to submit, Esc to exit)")
        except curses.error:
            pass
    
    # Refresh the screen
    stdscr.refresh()

async def edit_file(stdscr, websocket):
    global content, cursor_x, cursor_y, scroll_offset_y, output, error_message, input_mode
    
    # Configure curses
    curses.curs_set(1)  # Show cursor
    curses.noecho()     # Don't echo input
    stdscr.nodelay(True)  # Non-blocking input
    stdscr.keypad(True)   # Enable special keys
    
    # Clear previous state
    content = ""
    output = ""
    error_message = ""
    cursor_x = 0
    cursor_y = 0
    scroll_offset_y = 0
    
    # Open file on server
    await websocket.send(json.dumps({"command": "OPEN", "filename": filename}))
    
    # Set up screen
    height, width = stdscr.getmaxyx()
    editor_start_y = 2
    output_start_y = height // 2
    
    # Calculate editor height
    editor_height = output_start_y - editor_start_y - 1
    
    # Create input queue for running programs
    input_queue = asyncio.Queue()
    run_task = None  # Task for handling running program
    input_task = None  # Task for handling program input
    program_running = False  # Flag to track if a program is running
    
    # Main editing loop
    try:
        while True:
            # Draw editor
            draw_editor(stdscr, height, width, editor_start_y, output_start_y)
            
            # Position cursor correctly with scroll offset
            try:
                visible_cursor_y = editor_start_y + (cursor_y - scroll_offset_y)
                if not input_mode and 0 <= (cursor_y - scroll_offset_y) < editor_height:
                    stdscr.move(visible_cursor_y, 7 + cursor_x)  # +7 for line number display
            except curses.error:
                # Ignore cursor positioning errors
                pass
            
            # Handle server messages
            try:
                # Non-blocking check for messages from server
                message = await asyncio.wait_for(websocket.recv(), timeout=0.01)
                data = json.loads(message)
                
                if data["command"] == "LOAD":
                    content = data["content"]
                elif data["command"] == "UPDATE":
                    content = data["content"]
                elif data["command"] == "OUTPUT":
                    output = data["output"]
                    # If output received, the program might be running or finished
                    program_running = not data.get("finished", False)
                    if not program_running and input_mode:
                        input_mode = False
                        if input_task and not input_task.done():
                            input_task.cancel()
                elif data["command"] == "ERROR":
                    error_message = data["message"]
                    # Don't append to output so we don't duplicate
                    if "text must be False" in error_message:
                        error_message = "Curses error: try disabling user input mode for this program."
                    # Reset input mode on error
                    program_running = False
                    if input_mode:
                        input_mode = False
                        if input_task and not input_task.done():
                            input_task.cancel()
                elif data["command"] == "PROGRAM_STARTED":
                    program_running = True
                    output = "Program running...\n"
                    error_message = ""
                elif data["command"] == "PROGRAM_FINISHED":
                    program_running = False
                    if input_mode:
                        input_mode = False
                        if input_task and not input_task.done():
                            input_task.cancel()
            except asyncio.TimeoutError:
                # No message from server, continue processing user input
                pass
            
            # Check if we have input from running program
            if not input_queue.empty() and program_running:
                user_input = await input_queue.get()
                output += f"> {user_input}"  # Echo input in output area
                
            # Handle user input
            try:
                key = stdscr.getch()
            except Exception:
                key = -1  # No input
            
            if key == -1:
                # No input, continue
                await asyncio.sleep(0.05)
                continue
            
            # Skip key processing if we're in input mode
            if input_mode:
                await asyncio.sleep(0.05)
                continue
            
            # Process key commands
            if key == 24:  # Ctrl+X - exit
                # Save and close file
                await websocket.send(json.dumps({
                    "command": "EDIT",
                    "filename": filename,
                    "content": content
                }))
                await websocket.send(json.dumps({"command": "CLOSE", "filename": filename}))
                break
                
            elif key == 18:  # Ctrl+R - run
                # Save and run file
                await websocket.send(json.dumps({
                    "command": "EDIT",
                    "filename": filename,
                    "content": content
                }))
                await websocket.send(json.dumps({"command": "RUN", "filename": filename}))
                output = "Running program...\n"
                error_message = ""
                program_running = True
                
            elif key == 9 or key == ord('i'):  # Tab key or 'i' key for input mode
                if program_running and not input_mode:
                    input_mode = True
                    input_task = asyncio.create_task(
                        handle_program_input(stdscr, websocket, input_queue)
                    )
                    
            elif key == curses.KEY_UP:
                # Move cursor up
                if cursor_y > 0:
                    cursor_y -= 1
                    # Adjust position on line
                    content_lines = content.split('\n')
                    if cursor_y < len(content_lines) and cursor_x > len(content_lines[cursor_y]):
                        cursor_x = len(content_lines[cursor_y])
                    # Adjust scroll position
                    adjust_scroll_position(cursor_y, editor_height)
                
            elif key == curses.KEY_DOWN:
                # Move cursor down
                content_lines = content.split('\n')
                if cursor_y < len(content_lines) - 1:
                    cursor_y += 1
                    # Adjust position on line
                    if cursor_y < len(content_lines) and cursor_x > len(content_lines[cursor_y]):
                        cursor_x = len(content_lines[cursor_y])
                    # Adjust scroll position
                    adjust_scroll_position(cursor_y, editor_height)
                
            elif key == curses.KEY_LEFT:
                # Move cursor left
                if cursor_x > 0:
                    cursor_x -= 1
                elif cursor_y > 0:  # Move to end of previous line
                    cursor_y -= 1
                    content_lines = content.split('\n')
                    if cursor_y < len(content_lines):
                        cursor_x = len(content_lines[cursor_y])
                    # Adjust scroll position
                    adjust_scroll_position(cursor_y, editor_height)
                
            elif key == curses.KEY_RIGHT:
                # Move cursor right
                content_lines = content.split('\n')
                if cursor_y < len(content_lines) and cursor_x < len(content_lines[cursor_y]):
                    cursor_x += 1
                elif cursor_y < len(content_lines) - 1:  # Move to start of next line
                    cursor_y += 1
                    cursor_x = 0
                    # Adjust scroll position
                    adjust_scroll_position(cursor_y, editor_height)
                
            elif key in (curses.KEY_BACKSPACE, 8, 127):  # Backspace
                content_lines = content.split('\n')
                if cursor_x > 0:  # Remove character before cursor
                    if cursor_y < len(content_lines):
                        line = content_lines[cursor_y]
                        content_lines[cursor_y] = line[:cursor_x-1] + line[cursor_x:]
                        cursor_x -= 1
                elif cursor_y > 0:  # Join with previous line
                    if cursor_y < len(content_lines):
                        prev_line_len = len(content_lines[cursor_y-1])
                        content_lines[cursor_y-1] += content_lines[cursor_y]
                        content_lines.pop(cursor_y)
                        cursor_y -= 1
                        cursor_x = prev_line_len
                
                # Reconstruct content and save
                content = '\n'.join(content_lines)
                await websocket.send(json.dumps({
                    "command": "EDIT",
                    "filename": filename,
                    "content": content
                }))
                
                
            elif key in (10, 13):  # Enter key
                content_lines = content.split('\n')
                if cursor_y < len(content_lines):
                    line = content_lines[cursor_y]
                    content_lines[cursor_y] = line[:cursor_x]
                    content_lines.insert(cursor_y + 1, line[cursor_x:])
                    cursor_y += 1
                    cursor_x = 0
                    
                    # Reconstruct content and save
                    content = '\n'.join(content_lines)
                    await websocket.send(json.dumps({
                        "command": "EDIT",
                        "filename": filename,
                        "content": content
                    }))
                    
                    # Adjust scroll position
                    adjust_scroll_position(cursor_y, editor_height)
                
            elif key == curses.KEY_DC:  # Delete key
                content_lines = content.split('\n')
                if cursor_y < len(content_lines):
                    line = content_lines[cursor_y]
                    if cursor_x < len(line):  # Delete character at cursor
                        content_lines[cursor_y] = line[:cursor_x] + line[cursor_x+1:]
                    elif cursor_y < len(content_lines) - 1:  # Join with next line
                        content_lines[cursor_y] += content_lines[cursor_y+1]
                        content_lines.pop(cursor_y+1)
                    
                    # Reconstruct content and save
                    content = '\n'.join(content_lines)
                    await websocket.send(json.dumps({
                        "command": "EDIT",
                        "filename": filename,
                        "content": content
                    }))
                
            elif key == 9:  # Tab key
                content_lines = content.split('\n')
                if cursor_y < len(content_lines):
                    line = content_lines[cursor_y]
                    content_lines[cursor_y] = line[:cursor_x] + "    " + line[cursor_x:]
                    cursor_x += 4
                    
                    # Reconstruct content and save
                    content = '\n'.join(content_lines)
                    await websocket.send(json.dumps({
                        "command": "EDIT",
                        "filename": filename,
                        "content": content
                    }))
                
            elif 32 <= key <= 126:  # Printable characters
                content_lines = content.split('\n')
                if cursor_y >= len(content_lines):
                    # Add empty lines if needed
                    while cursor_y >= len(content_lines):
                        content_lines.append("")
                
                # Insert character at cursor
                line = content_lines[cursor_y]
                content_lines[cursor_y] = line[:cursor_x] + chr(key) + line[cursor_x:]
                cursor_x += 1
                
                # Reconstruct content and save
                content = '\n'.join(content_lines)
                await websocket.send(json.dumps({
                    "command": "EDIT",
                    "filename": filename,
                    "content": content
                }))
            
            # Recalculate editor height in case terminal size changed
            height, width = stdscr.getmaxyx()
            output_start_y = height // 2
            editor_height = output_start_y - editor_start_y - 1
            
            # Adjust scroll position based on cursor
            adjust_scroll_position(cursor_y, editor_height)
                
    except websockets.exceptions.ConnectionClosed:
        # Connection closed, clean up
        error_message = "Connection to server lost"
        draw_editor(stdscr, height, width, editor_start_y, output_start_y)
        stdscr.getch()  # Wait for keypress
        return False
    except Exception as e:
        # Handle other exceptions
        error_message = f"Error: {str(e)}\n{traceback.format_exc()}"
        draw_editor(stdscr, height, width, editor_start_y, output_start_y)
        stdscr.getch()  # Wait for keypress
        return False
    
    return True

async def curses_main(stdscr, websocket):
    # Configure curses
    curses.start_color()
    curses.use_default_colors()
    curses.curs_set(0)  # Hide cursor initially
    stdscr.clear()
    
    # Main program loop
    while True:
        # Show file selection screen
        if not await file_selection_screen(stdscr, websocket):
            break  # Exit if user cancels or error
        
        # Enter editor mode for selected file
        if not await edit_file(stdscr, websocket):
            continue  # Go back to file selection if editing fails

async def main():
    try:
        # Connect to server
        async with websockets.connect(SERVER_URI) as websocket:
            # Initialize curses
            # The key fix: Use curses.wrapper directly with an async function
            # that we'll await, instead of trying to run an event loop inside another event loop
            await curses_wrapper(websocket)
    except ConnectionRefusedError:
        print("Could not connect to server. Make sure the server is running.")
    except Exception as e:
        print(f"Error: {str(e)}")

# Custom wrapper for curses that works with async functions
async def curses_wrapper(websocket):
    # Initialize curses
    stdscr = curses.initscr()
    curses.noecho()
    curses.cbreak()
    stdscr.keypad(True)
    
    try:
        # Call our async function with the screen
        await curses_main(stdscr, websocket)
    finally:
        # Clean up curses
        curses.nocbreak()
        stdscr.keypad(False)
        curses.echo()
        curses.endwin()

if __name__ == "__main__":
    try:
        # This is the only place where asyncio.run() should be called
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProgram terminated by user")
    except Exception as e:
        print(f"Fatal error: {str(e)}")