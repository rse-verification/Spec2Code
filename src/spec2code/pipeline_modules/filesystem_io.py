import os
from typing import List, Optional, Iterable
import json
import shutil

def file_exists(file_path: str) -> bool:
    """
    Checks if a file exists.
    
    Args:
        file_path (str): The absolute path to the file.
    
    Returns:
        bool: True if the file exists, False otherwise.
    """
    return os.path.isfile(file_path)

def read_file(file_path: str) -> Optional[str]:
    """
    Reads the content of a file.
    
    Args:
        file_path (str): The absolute path to the file.
    
    Returns:
        Optional[str]: The content of the file if successful, None otherwise.
    """
    if not os.path.isfile(file_path):
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    except Exception as e:
        print(f"Error reading file {file_path}: {e}")
        return None

def write_file(file_path: str, content: str, mode: str = 'w') -> bool:
    """
    Writes content to a file.
    
    Args:
        file_path (str): The absolute path to the file.
        content (str): The content to write to the file.
        mode (str, optional): The mode for writing (default is 'w' for overwrite).
    
    Returns:
        bool: True if writing was successful, False otherwise.
    """
    # Ensure the directory exists
    directory = os.path.dirname(file_path)
    if not os.path.isdir(directory):
        create_directory(directory)

    try:
        with open(file_path, mode, encoding='utf-8') as file:
            file.write(content)
        return True
    except Exception as e:
        print(f"Error writing to file {file_path}: {e}")
        return False

def export_json(file_path: str, data: dict) -> bool:
    """
    Exports data to a JSON file.
    """
    directory = os.path.dirname(file_path)
    if directory and not os.path.isdir(directory):
        create_directory(directory)

    try:
        with open(file_path, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=4)
        return True
    except Exception as e:
        print(f"Error exporting JSON to file {file_path}: {e}")
        return False

def list_files(directory_path: str) -> List[str]:
    """
    Lists all files in a directory.
    
    Args:
        directory_path (str): The absolute path to the directory.
    
    Returns:
        List[str]: A list of filenames in the directory.
    """
    if not os.path.isdir(directory_path):
        return []
    
    try:
        return os.listdir(directory_path)
    except Exception as e:
        print(f"Error listing files in directory {directory_path}: {e}")
        return []

def delete_file(file_path: str) -> bool:
    """
    Deletes a file.
    
    Args:
        file_path (str): The absolute path to the file.
    
    Returns:
        bool: True if deletion was successful, False otherwise.
    """
    if not os.path.isfile(file_path):
        return False
    
    try:
        os.remove(file_path)
        return True
    except Exception as e:
        print(f"Error deleting file {file_path}: {e}")
        return False

def directory_exists(directory_path: str) -> bool:
    """
    Checks if a directory exists.
    
    Args:
        directory_path (str): The absolute path to the directory.
    
    Returns:
        bool: True if the directory exists, False otherwise.
    """
    return os.path.isdir(directory_path)

def create_directory(directory_path: str) -> bool:
    """
    Creates a directory if it does not exist.
    
    Args:
        directory_path (str): The absolute path to the directory.
    
    Returns:
        bool: True if the directory was created or already exists, False otherwise.
    """
    try:
        os.makedirs(directory_path, exist_ok=True)
        return True
    except Exception as e:
        print(f"Error creating directory {directory_path}: {e}")
        return False

def delete_directory(directory_path: str) -> bool:
    """
    Deletes a directory if it exists.
    
    Args:
        directory_path (str): The absolute path to the directory.
    
    Returns:
        bool: True if deletion was successful, False otherwise.
    """
    if not os.path.isdir(directory_path):
        return False
    
    try:
        os.rmdir(directory_path)
        return True
    except Exception as e:
        print(f"Error deleting directory {directory_path}: {e}")
        return False

def list_directories(parent_directory: str) -> List[str]:
    """
    Lists all directories in a given parent directory.
    
    Args:
        parent_directory (str): The absolute path to the parent directory.
    
    Returns:
        List[str]: A list of directory names inside the parent directory.
    """
    if not os.path.isdir(parent_directory):
        return []
    
    try:
        return [d for d in os.listdir(parent_directory) if os.path.isdir(os.path.join(parent_directory, d))]
    except Exception as e:
        print(f"Error listing directories in {parent_directory}: {e}")
        return []
def copy_files(
    src_dir: str,
    dst_dir: str,
    *,
    extensions: Iterable[str] | None = None,   # e.g. [".h"]
    recursive: bool = True,
    overwrite: bool = True,
    keep_tree: bool = False,                   # keep relative subfolders under dst_dir
) -> dict:
    """
    Copies files from src_dir to dst_dir.

    Returns a dict:
      {
        "success": bool,
        "copied": [<dst paths>],
        "skipped": [<src paths>],
        "error": <str|None>
      }
    """
    result = {"success": False, "copied": [], "skipped": [], "error": None}

    if not os.path.isdir(src_dir):
        result["error"] = f"Source directory does not exist: {src_dir}"
        print(result["error"])
        return result

    create_directory(dst_dir)

    def _match_ext(filename: str) -> bool:
        if not extensions:
            return True
        return any(filename.endswith(ext) for ext in extensions)

    try:
        if recursive:
            for root, _, files in os.walk(src_dir):
                for name in files:
                    if not _match_ext(name):
                        continue

                    src = os.path.join(root, name)
                    if keep_tree:
                        rel = os.path.relpath(root, src_dir)
                        out_dir = os.path.join(dst_dir, rel) if rel != "." else dst_dir
                        create_directory(out_dir)
                        dst = os.path.join(out_dir, name)
                    else:
                        dst = os.path.join(dst_dir, name)

                    if (not overwrite) and os.path.exists(dst):
                        result["skipped"].append(src)
                        continue

                    shutil.copy2(src, dst)
                    result["copied"].append(dst)
        else:
            for name in os.listdir(src_dir):
                src = os.path.join(src_dir, name)
                if not os.path.isfile(src):
                    continue
                if not _match_ext(name):
                    continue

                dst = os.path.join(dst_dir, name)
                if (not overwrite) and os.path.exists(dst):
                    result["skipped"].append(src)
                    continue

                shutil.copy2(src, dst)
                result["copied"].append(dst)

        result["success"] = True
        return result

    except Exception as e:
        msg = f"Error copying files from {src_dir} to {dst_dir}: {e}"
        result["error"] = msg
        print(msg)
        return result
