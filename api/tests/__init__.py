import sys
import pprint

def DEBUG_PRINT(**kwargs):
    pp = pprint.PrettyPrinter(indent=4)
    objstr = "".join(f"[{k}:{v}]\n" for k, v in kwargs.items())
    pp.pprint(f"\t[DEBUG] {str(__file__)} - {sys._getframe(1).f_lineno}: {objstr}")
