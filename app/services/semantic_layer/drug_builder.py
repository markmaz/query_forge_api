import logging
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class DrugBuilder:
    def __init__(self, drug_code_mapping_agent) -> None:
        """
        drug_code_mapping_agent: object exposing map_drug_code(drug: str)
            -> {"best_codes": {...}, ...}
        """
        self.drug_code_mapping_agent = drug_code_mapping_agent

    def build_drugs(self, medications: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """
        Convert NER medication entities into a normalized drug mapping dict.

        medications items look like:
        {
          "type": "description" | "code",
          "drug": "<string>",
          "negation": bool,
          "logic": "AND" | "OR" | ...
        }

        Returns:
            {
              "<display_key>": {
                 "name": <display_name>,
                 "code": <code_string>,
                 "negation": bool,
                 "logic": "AND"/"OR",
              },
              ...
            }
        """
        description_entities: List[Dict[str, Any]] = []
        code_entities: List[Dict[str, Any]] = []

        # Split description vs code entities
        for ent in medications:
            t = ent.get("type")
            if t == "description":
                description_entities.append(ent)
            elif t == "code":
                code_entities.append(ent)
            else:
                logger.debug("Unexpected drug type from NER: %r", t)

        dict_drug: Dict[str, Dict[str, Any]] = {}

        # 1) Description-based drugs → call mapping pipeline
        for ent in description_entities:
            raw_drug = ent["drug"]
            negation = ent.get("negation")
            base_logic = ent.get("logic")

            mapping = self.drug_code_mapping_agent.map_drug_code(raw_drug)
            best_code_dict = mapping.get("best_codes") or {}

            # best_code_dict: {display_name: [ndc1, ndc2, ...]}
            for idx, (best_drug, ndc_list) in enumerate(best_code_dict.items()):
                # Normalize display name and codes
                name = best_drug  # or best_drug.capitalize() if you prefer
                codes_str = ", ".join(ndc_list)
                logic = base_logic if idx == 0 else "OR"

                key = f"{name}-{codes_str[:100]}"

                dict_drug[key] = {
                    "name": name,
                    "code": codes_str,
                    "negation": negation,
                    "logic": logic,
                }

        # 2) Code-based drugs → normalize NDC and echo back
        for ent in code_entities:
            raw_code = ent["drug"]
            negation = ent.get("negation")
            logic = ent.get("logic")

            if not raw_code:
                logger.debug("Empty drug code encountered; skipping entity: %r", ent)
                continue

            try:
                code = self.ndc_to_11(raw_code) if len(raw_code) < 11 else re.sub(r"\D", "", raw_code)
            except ValueError:
                logger.warning("Invalid NDC code %r; using raw code as-is", raw_code)
                code = raw_code

            dict_drug[code] = {
                "name": code,
                "code": code,
                "negation": negation,
                "logic": logic,
            }

        return dict_drug

    def ndc_to_11(self, raw: str) -> str:
        """
        Convert a 9- or 10-digit NDC (with or without dashes) to the
        11-digit 5-4-2 layout, returned *without* dashes.

        Accepted dashed patterns (labeler-product-package):
            4-3-2, 4-4-1, 5-2-2, 5-3-1, 4-4-2, 5-3-2, 5-4-1
        Undashed: 9–11 digits, digits only (11 = already normalized).

        Args:
            raw: raw NDC code

        Returns:
            11-digit NDC code without dash
        """
        raw = raw.strip()

        # ─────────────────── dashed input ────────────────────
        if "-" in raw:
            segs = raw.split("-")
            if len(segs) != 3 or not all(s.isdigit() for s in segs):
                raise ValueError("Dashed NDC must have three numeric parts")

            labeler, product, package = segs

            # pad each segment to its canonical length
            labeler = labeler.zfill(5)  # 4- or 5-digit → 5
            product = product.zfill(4)  # 2-,3-,4-digit → 4
            package = package.zfill(2)  # 1- or 2-digit → 2

            return f"{labeler}{product}{package}"

        # ─────────────── undashed 9–11-digit input ───────────────
        ndc = re.sub(r"\D", "", raw)  # strip non-digits

        if len(ndc) == 11:
            # Already normalized
            return ndc

        if len(ndc) == 9:
            ndc = ndc.zfill(10)

        if len(ndc) != 10:
            raise ValueError("Need 9, 10, or 11 digits when undashed")

        # heuristic to guess which segment is short
        if ndc[4] == "0":  # likely 4-4-2 → pad labeler
            return "0" + ndc
        if ndc[8] == "0":  # likely 5-4-1 → pad package
            return ndc[:-2] + "0" + ndc[-2:]
        # default: treat as 5-3-2 → pad product
        return ndc[:5] + "0" + ndc[5:]
