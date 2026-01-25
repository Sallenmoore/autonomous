import re


class TaskRouterBase:
    """
    Maps URL paths to Task Functions.
    Acts as the central registry for all background tasks.
    """

    # Format: (Regex Pattern, Function Object)

    @classmethod
    def resolve(cls, path):
        """
        Parses the path, finds the matching function, and extracts arguments.
        Returns: (function_obj, kwargs_dict) or (None, None)
        """
        for pattern, func in cls.ROUTES:
            match = re.match(pattern, path)
            if match:
                return func, match.groupdict()
        return None, None

    ROUTES = []
