# pipeline_modules/runtime.py
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from spec2code.pipeline_modules.experiment_parameters import initialize_llms
from spec2code.pipeline_modules.verify import initialize_solvers
from spec2code.pipeline_modules.critics.critics_runner import build_default_critics

@dataclass(frozen=True)
class Runtime:
    llms_available: Dict[str, Any]
    solvers: Any
    critics: List[Any]

def build_runtime(*, llm_names: Optional[List[str]] = None, solvers: Optional[List[str]] = None) -> Runtime:
    if solvers is None:
        solvers = initialize_solvers()
    return Runtime(
        llms_available=initialize_llms(llm_names),
        solvers=solvers,
        critics=build_default_critics(solvers=solvers),
    )
