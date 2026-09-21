import json
import socket

import httpx
from prometheus_client.parser import text_string_to_metric_families


def main() -> None:
    addresses = sorted({item[4][0] for item in socket.getaddrinfo("api", 8000, socket.AF_INET)})
    output: dict = {"instances": {}, "totals": {}}
    with httpx.Client(trust_env=False, timeout=3) as client:
        for address in addresses:
            response = client.get(f"http://{address}:8000/internal/metrics")
            response.raise_for_status()
            metrics = response.text
            values = {}
            for family in text_string_to_metric_families(metrics):
                for sample in family.samples:
                    if sample.name.endswith("_created"):
                        continue
                    if (
                        sample.name.startswith("sentinel_")
                        or sample.name == "process_resident_memory_bytes"
                    ):
                        key = sample.name + json.dumps(sample.labels, sort_keys=True)
                        values[key] = sample.value
                        output["totals"][key] = output["totals"].get(key, 0) + sample.value
            output["instances"][address] = values
    print(json.dumps(output))


if __name__ == "__main__":
    main()
