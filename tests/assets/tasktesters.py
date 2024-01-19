import time

from rq import get_current_job


def mylongtask():
    job = get_current_job()
    print(f"\nCurrent job 1: {job.id}")
    time.sleep(10)
    # print(f"\nCurrent job 2: {job.id}")
    return  # job.id


def mytask(a, b):
    job = get_current_job()
    print(f"\nCurrent job: {job.id}")
    time.sleep(2)
    return a + b


def myfailedtask(a, b):
    job = get_current_job()
    print(f"\nCurrent job: {job.id}")
    time.sleep(2)
    return int(a) + str(b)
