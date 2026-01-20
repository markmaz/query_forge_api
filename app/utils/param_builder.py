from urllib.parse import quote


class ParamBuilder:
    def __init__(self):
        self.params = []

    def add_param(self, key: str, value: str, encode: bool = False):
        """
        Adds a Sigma embed parameter (:key=value).
        """
        if encode:
            value = quote(value, safe="")  # Encode JWT safely

        self.params.append(f":{key}={value}")
        return self

    def __str__(self):
        if not self.params:
            return ""
        return f"?{'&'.join(self.params)}"

    def get_query_string(self):
        return str(self)