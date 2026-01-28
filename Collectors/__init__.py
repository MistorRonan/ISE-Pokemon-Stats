import pkgutil
import importlib
from datetime import datetime

# A list to store all the found 'collect' functions
all_collectors = []

# 1. Iterate through all modules in the current package directory
for loader, module_name, is_pkg in pkgutil.iter_modules(__path__):
    # 2. Dynamically import the module
    # We use relative import syntax (e.g., '.module_name')
    module = importlib.import_module(f".{module_name}", package=__name__)

    # 3. Check if the module has a 'collect' attribute and if it's callable
    if hasattr(module, 'collect'):
        collect_func = getattr(module, 'collect')
        if callable(collect_func):
            all_collectors.append(collect_func)


def run_all(param=""):
    """
    Execute every collected function and attach timestamps.

    Returns a dictionary with:
      - 'started_at': ISO timestamp when run_all began
      - 'completed_at': ISO timestamp when run_all finished
      - 'results': list of per-collector results, each including:
            {
                "collector": <function_name>,
                "timestamp": <ISO time when this result was obtained>,
                "result": <original result from collect()>
            }
    """
    started_at = datetime.utcnow().isoformat() + "Z"

    results = []
    for func in all_collectors:
        result_time = datetime.utcnow().isoformat() + "Z"
        results.append(
            {
                "collector": getattr(func, "__name__", "unknown"),
                "timestamp": result_time,
                "result": func(param),
            }
        )

    completed_at = datetime.utcnow().isoformat() + "Z"

    return {
        "started_at": started_at,
        "completed_at": completed_at,
        "results": results,
    }