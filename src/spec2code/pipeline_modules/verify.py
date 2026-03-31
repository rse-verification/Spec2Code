import re
import time
import subprocess
from typing import List, Tuple, Dict
from spec2code.pipeline_modules.subprocess_creator import run_command

def run_frama_c_print(c_file_path: str, debug: bool = False) -> str:
    """
    Runs `frama-c -print` on a C file and returns the parsed output as a string.
    
    Args:
        c_file_path (str): Path to the original C file.
        debug (bool): If True, enables debugging prints.
    
    Returns:
        str: Parsed C code output from Frama-C.
    """
    command = ["frama-c", "-print", c_file_path]
    
    if debug:
        print(f"Running command: {' '.join(command)}")
    
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        
        if debug:
            print("Frama-C output successfully retrieved.")
        
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running Frama-C: {e.stderr}")
        return ""
    except FileNotFoundError:
        print("Error: Frama-C is not installed or not found in PATH.")
        return ""

def get_line_number_in_parsed_code(c_file_path: str, line_number: int, debug: bool = False) -> str:
    """
    Retrieves a specific line from the parsed version of a C file using Frama-C -print.
    
    Args:
        c_file_path (str): The path to the C file to parse.
        line_number (int): The line number to retrieve.
        debug (bool): If True, enables debugging prints.
    
    Returns:
        str: The corresponding line of code in the parsed C file.
    """
    parsed_code = run_frama_c_print(c_file_path, debug)
    
    if not parsed_code:
        return ""
    
    parsed_code_lines = parsed_code.split("\n")
    
    if line_number < 1 or line_number > len(parsed_code_lines):
        print(f"Warning: Line number {line_number} is out of range for {c_file_path}.")
        return ""
    
    line = parsed_code_lines[line_number - 1].strip()
    
    if debug:
        print(f"Retrieved line {line_number} from parsed output: {line}")
    
    return line

def initialize_solvers() -> List[str]:
    """
    Retrieves the list of solvers available in Why3.
    
    Returns:
        List[str]: A list of solver names available in Why3.
    """
    try:
        # Run the Why3 solver detection command
        result = subprocess.run(
            ["why3", "config", "detect"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        
        # Extract lines from the output
        output_lines = result.stdout.split("\n")
        
        if len(output_lines) < 2:
            raise RuntimeError("Unexpected Why3 output format.")
        
        # Extract solvers file path from the second last line
        solvers_path = output_lines[-2].partition("/")[1] + output_lines[-2].partition("/")[2]
        
        return parse_solvers_from_file(solvers_path)
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        print(f"Error executing Why3 command: {e}")
        return []

def parse_solvers_from_file(file_path: str) -> List[str]:
    """
    Parses the solvers configuration file to extract solver names.
    
    Args:
        file_path (str): Path to the Why3 solvers configuration file.
    
    Returns:
        List[str]: A list of solver names.
    """
    solver_names = []
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            solvers_list = file.read().split("[partial_prover]")[1:]
            
            # Extract solver names using regex
            for solver_entry in solvers_list:
                match = re.search(r'name = "(.*?)"', solver_entry)
                if match:
                    solver_names.append(match.group(1))
    except FileNotFoundError:
        print(f"Error: Solvers configuration file not found at {file_path}.")
    except Exception as e:
        print(f"Error reading solvers file: {e}")
    
    return solver_names

def get_functions(lines: List[str]) -> List[Tuple[int, str]]:
    """
    Extracts function definitions from a list of lines in a C file.
    
    Args:
        lines (List[str]): The lines of the file.
    
    Returns:
        List[Tuple[int, str]]: A list of tuples containing line number and function name.
    """
    functions = []
    function_pattern = re.compile(
        r'^(?:static\s+)?(?:unsigned\s+|signed\s+)?(?:void|bool|int|double|float|char|long|short|struct\s+\w+|enum\s+\w+|uint|ulong)\s+(\w+)\s*\('
    )
    
    for i, line in enumerate(lines):
        match = function_pattern.match(line.strip())
        if match:
            functions.append((i + 1, match.group(1)))
    
    return functions


def remove_existing_acsl_specification(code: str) -> str:
    """
    Removes existing ACSL formal specifications from the provided C code.
    
    Args:
        code (str): The C code from which ACSL specifications should be removed.
    
    Returns:
        str: The updated code without existing ACSL specifications.
    """
    acsl_pattern = re.compile(r'/\*@(.*?)\*/', re.DOTALL)  # Matches ACSL comments
    return re.sub(acsl_pattern, '', code)

def extract_function_by_signature(code: str, function_signature: str) -> str:
    """
    Extracts the function signature and implementation of a specified function,
    removing everything else from the provided C code while correctly handling nested braces.
    
    Args:
        code (str): The C code containing multiple functions.
        function_signature (str): The function signature to extract (e.g., 'int add(int* a, int* b);').
    
    Returns:
        str: The extracted function definition with its implementation or an empty string if not found.
    """
    function_name = function_signature.split('(')[0].split()[-1]  # Extract function name
    
    # Match function signature
    signature_pattern = re.compile(rf'{re.escape(function_signature).rstrip(";")}\s*\{{', re.DOTALL)
    match = signature_pattern.search(code)
    
    if not match:
        return ""  # Function signature not found
    
    start_index = match.start()
    brace_count = 0
    in_function = False
    
    # Find the full function body by counting braces
    for i in range(start_index, len(code)):
        if code[i] == '{':
            if not in_function:
                function_start = i
                in_function = True
            brace_count += 1
        elif code[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                function_end = i + 1
                return code[start_index:function_end]  # Return full function
    
    return ""  # Return empty string if function not found


def add_input_to_function(
    signature: str,
    formal_specification: str,
    natural_language_specification: str,
    header_content: str,
    interface_content: str,
    code: str
) -> str:
    """
    Finds a function with the specified name and adds additional content before it, including:
    1. Natural language specification
    2. Header file content
    3. Interface content
    4. Formal specification
    5. Function signature
    
    Args:
        signature (str): The signature of the function to modify.
        formal_specification (str): The formal specification to add above the function.
        natural_language_specification (str): The natural language description of the function.
        header_content (str): The header file content.
        interface_content (str): The interface content.
        code (str): The C code as a string.
    
    Returns:
        str: The updated code with the additional content added above the function.
    """
    code_lines = code.split("\n")
    function_definitions = get_functions(code_lines)

    signature_list = [f'{signature}']
    function_in_signature = get_functions(signature_list)
    
    for line_number, detected_function_name in function_definitions:
        if detected_function_name == function_in_signature[0][1]:
            # Insert additional content above the function definition
            insert_content = (
                f"/* Natural Language Specification \n{natural_language_specification}  */\n"
                f"/* Header File Content */\n{header_content}\n"
                f"/* Interface Content */\n{interface_content}\n"
                f"/* Formal Specification */\n{formal_specification}\n"
                f"{signature}"
            )
            code_lines.insert(line_number - 1, insert_content)
            return "\n".join(code_lines)
    
    print(f"Warning: The formal specification was not added to the code. Signature '{signature}' not found in the code.")
    return code
