import sys
import pprint

def debug_print(*args, **kwargs):
    frame = sys._getframe(1)
    logger = kwargs.pop('logger', pprint.PrettyPrinter(indent=4).pprint)
    trace = f"<{frame.f_code.co_filename}:{frame.f_lineno}>"
    logger(f"===[DEBUG]=== {trace}")
    if args:
        logger("ARGS:")
        logger(args)
    if kwargs:
        logger("KWARGS:")
        logger(kwargs)
    logger("=" * 80)
    logger("")