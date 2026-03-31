from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class PipelineConfig:
    name: str
    case_study: str
    selected_prompt_template: str
    llms_used: List[str]
    n_programs_generated: int
    output_folder: str
    temperature: float = 0.7
    debug: bool = False
    natural_spec_path: Optional[str] = None
    interface_path: Optional[str] = None
    signature_path: Optional[str] = None
    headers_dir: Optional[str] = None
    include_dirs: List[str] = None
    copy_headers_to_output: bool = True
    critics: List[str] = None

    headers_manifest: Optional[Dict[str, str]] = None

    def __post_init__(self) -> None:
        if self.include_dirs is None:
            self.include_dirs = []
        else:
            self.include_dirs = list(self.include_dirs)

        # headers_dir implies include dir
        if self.headers_dir and self.headers_dir not in self.include_dirs:
            self.include_dirs.append(self.headers_dir)

        if self.critics is None:
            self.critics = ["compile"] 
        else:
            self.critics = list(self.critics)

        if self.headers_manifest is not None:
            self.headers_manifest = dict(self.headers_manifest)

    @staticmethod
    def from_dict(cfg: Dict[str, Any], debug: bool = False) -> "PipelineConfig":
        return PipelineConfig(
            name=str(cfg.get("name", "unnamed_config")),
            case_study=str(cfg.get("case_study", "default")),
            selected_prompt_template=str(cfg.get("selected_prompt_template", "zero-shot")),
            llms_used=list(cfg.get("llms_used", [])),
            n_programs_generated=int(cfg.get("n_programs_generated", 1)),
            output_folder=str(cfg.get("output_folder", "./output/")),
            temperature=float(cfg.get("temperature", 0.7)),
            debug=bool(cfg.get("debug", debug)),
            headers_dir=(cfg.get("headers_dir") if cfg.get("headers_dir") else None),
            include_dirs=list(cfg.get("include_dirs", [])),
            copy_headers_to_output=bool(cfg.get("copy_headers_to_output", True)),
            critics=list(cfg.get("critics", ["compile"])),
            headers_manifest=(dict(cfg.get("headers_manifest")) if cfg.get("headers_manifest") else None),
        )

    def execute(self) -> None:
        from pipeline import execute_pipeline 

        execute_pipeline(
            case_study=self.case_study,
            selected_prompt_template=self.selected_prompt_template,
            llms_used=self.llms_used,
            n_programs_generated=self.n_programs_generated,
            output_folder=self.output_folder,
            name=self.name,
            temperature=self.temperature,
            debug=self.debug,
            headers_dir=self.headers_dir,
            include_dirs=self.include_dirs,
            copy_headers_to_output=self.copy_headers_to_output,
            critics_enabled=self.critics,
            headers_manifest=self.headers_manifest, 
        )
