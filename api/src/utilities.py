import sys
import pprint

def DEBUG_PRINT(*args, **kwargs):
    pp = pprint.PrettyPrinter(indent=4)
    objstr = "".join(f"{v}\n" for v in args) + "".join(f"[{k}:{v}]\n" for k, v in kwargs.items())
    frame = sys._getframe(1)
    pp.pprint(f"\t[DEBUG] <{frame.f_code.co_filename}:{frame.f_lineno}> {objstr}")
