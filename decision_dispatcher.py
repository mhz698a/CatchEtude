"""Classification dispatch and destination resolution."""
from __future__ import annotations
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any
import config
from classification_registry import ClassificationRegistry

class DecisionDispatcher:
    """Resolve configured decisions without depending on their IDs."""
    def __init__(self,panel=None,registry:ClassificationRegistry|None=None):
        self.panel=panel
        self.registry=registry or getattr(panel,"classification_registry",None) or ClassificationRegistry()

    def dispatch_subfolder_click(self,decision:dict[str,Any],name:str)->None:
        if self.panel is None:
            return
        handler=decision.get("handler")
        if handler=="keep":
            self.panel.keep_action_clicked.emit(name)
        elif handler=="linear_docs":
            self.panel.linear_docs_action_clicked.emit(name)
        elif handler=="move_to_subfolder":
            self.panel._remember_recent_subfolder(name)
            self.panel.subfolder_clicked.emit(name)

    def requires_year(self,decision:dict[str,Any])->bool:
        return decision.get("year_mode","none")=="required"

    def requires_internal(self,decision:dict[str,Any])->bool:
        return bool(decision.get("requires_internal",False))

    @staticmethod
    def _path_context(year:int|None,source:Path|None=None)->dict[str,str]:
        values={
            "BASE_INTERNAL":str(config.BASE_INTERNAL),
            "ONEDRIVE_DOCS":str(config.ONEDRIVE_DOCS),
            "ONEDRIVE_DOCTOS_FAMILIA":str(config.ONEDRIVE_DOCTOS_FAMILIA),
            "IMAGES_FOLDER":str(config.IMAGES_FOLDER),
            "MUSIC_FOLDER":str(config.MUSIC_FOLDER),
            "OVERWORLD_FOLDER":str(config.OVERWORLD_FOLDER),
            "ACROBAT_FOLDER":str(config.ACROBAT_FOLDER),
        }
        if year is not None:
            values["year"]=str(year)
            values["year_prefix"]=f"{year-2003:02d}"
        if source is not None:
            try:
                dt=datetime.fromtimestamp(source.stat().st_mtime)
                values["mtime_year"]=str(dt.year)
                values["mtime_month"]=dt.strftime("%Y-%m")
            except OSError:
                logging.warning("Could not read source timestamp for %s",source)
        return values

    @staticmethod
    def _expand_template(template:str,context:dict[str,str])->Path:
        expanded=str(template)
        for key,value in context.items():
            expanded=expanded.replace("{"+key+"}",value)
        expanded=os.path.expandvars(os.path.expanduser(expanded))
        if "{" in expanded or "}" in expanded:
            raise ValueError(f"Unresolved placeholder in classification path: {template}")
        return Path(expanded)

    def resolve_base_path(self,decision:dict[str,Any],year:int|None,source:Path|None=None)->Path|None:
        """Resolve base_path and select an immediate child matching folder_contains."""
        template=decision.get("base_path")
        if not isinstance(template,str) or not template.strip():
            return None
        context=self._path_context(year,source)
        parent=self._expand_template(template,context)
        contains=decision.get("folder_contains")
        if not contains:
            return parent
        contains=str(contains)
        for key,value in context.items():
            contains=contains.replace("{"+key+"}",value)
        if "{" in contains or "}" in contains:
            raise ValueError(
                f"Unresolved placeholder in folder_contains: {decision.get('folder_contains')}"
            )
        if parent.is_dir():
            try:
                matches=sorted(
                    (p for p in parent.iterdir() if p.is_dir() and str(contains).casefold() in p.name.casefold()),
                    key=lambda p:p.name.casefold(),
                )
                if matches:
                    return matches[0]
            except OSError:
                logging.exception("Could not search folder_contains=%r under %s",contains,parent)
        fallback=decision.get("folder_fallback")
        if isinstance(fallback,str) and fallback.strip():
            return self._expand_template(fallback,context)
        return parent

    def resolve_destination(self,decision:dict[str,Any],source:Path,year:int|None=None,subfolder:str|None=None,new_name:str|None=None)->Path:
        """Build the file destination by applying the selected decision definition."""
        source=Path(source)
        handler=decision.get("handler")
        if handler=="keep":
            return Path(config.CONFLICTS)/f"{new_name or source.stem}{source.suffix}"
        if handler=="linear_docs":
            try:
                modified=datetime.fromtimestamp(source.stat().st_mtime)
            except OSError:
                modified=datetime.now()
            base=self.resolve_base_path(decision,modified.year,source)
            if base is None:
                raise ValueError("Linear documentation decision has no base_path")
            destination_dir=base/modified.strftime("%Y-%m")
        elif handler=="move_to_subfolder":
            if self.requires_year(decision) and year is None:
                raise ValueError(f"Decision {decision.get('id')} requires a selected year")
            destination_dir=self.resolve_base_path(decision,year,source)
            if destination_dir is None:
                raise ValueError(f"Decision {decision.get('id')} has no resolvable base_path")
            if subfolder:
                if (
                    Path(subfolder).is_absolute()
                    or "/" in subfolder
                    or "\\" in subfolder
                    or Path(subfolder).name != subfolder
                    or subfolder in {".", ".."}
                ):
                    raise ValueError(f"Invalid destination subfolder: {subfolder!r}")
                destination_dir=destination_dir/subfolder
        else:
            raise ValueError(f"Unsupported decision handler: {handler!r}")
        destination_dir.mkdir(parents=True,exist_ok=True)
        return destination_dir/f"{new_name or source.stem}{source.suffix}"
