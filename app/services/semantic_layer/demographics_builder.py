from typing import Dict


class DemographicsBuilder():
    def build_demographics(self, entity: Dict) -> Dict:
        def bounds(key: str):
            v = entity.get(key)
            if not v:
                return None
            return {
                "lower_bound": v.get("lower_bound"),
                "upper_bound": v.get("upper_bound"),
            }

        return {
            "dx_year": bounds("dx_year"),
            "age": bounds("age"),
            "gender": entity.get("gender"),
            "location": entity.get("location")
        }
