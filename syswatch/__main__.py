import json
import time

from .collector import Collector, system_info


def main():
    collector = Collector()
    time.sleep(1)
    print(json.dumps({"system": system_info(), **collector.sample()}, indent=2))


if __name__ == "__main__":
    main()
