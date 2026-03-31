# vernfr
Verification of Non-Functional Requirements (NFR)

## Testing
To test, there is the test script testscript.sh
Currently, it uses the test-spec defined in vernfr.ml

## Building
to build run 'dune build @install' and 'dune install' from root folder

## Checks
The following nfr checks are available:

### Check outgoing calls (-nfr-check-calls)
Checks that all outgoing calls to other modules are defined as allowed in the interface specification.
Emits a warning if this is the case.
The checks are implemented for call instructions, and local initialisations with function calls.
Does not emit warning if the function has local (static) storage.

### Check entry (-nfr-entry-check) 
Checks that only the function defined as entry functions in the specifications are declared.
Emits a warning if this is the case.
Does not emit a warning for functions declared with local (static) storage.

### Check fun defs (-nfr-fun-defs)
Emits a warning if a function definition is detected, intended to be used for header files.

### Check static (-nfr-static-vars)
Emits a warning for any declared variable that is not declared with static storage.
Note: due to normalisation, this might not work for variables that are declared but not used.


### Check Function pointers (-nfr-fun-ptrs)
Emits a warning if any call is made through a function pointer.
The check is for all expressions (which include parameters and function calls to function pointers). This is quite a crude check.

### Check explicit initialisation (-nfr-proper-init)
Emits a warning if global variable is used without either explicit initalisation or being assigned to before the first usage. Takes into account the call order defined for entry functions in the ispec 
NOTE: Does not afaik consider assignments in external calls. It is still sound but if a variable is assigned to through a pointer in an external call, we might emit spurious warning.

# TODOS
Validate interface specifications  
Add rule numbers