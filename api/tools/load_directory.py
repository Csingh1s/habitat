from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
from uuid import uuid4

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Local-only inspection directory HTTP load check.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--rate", type=float, default=4)
    parser.add_argument("--requests", type=int, default=40)
    parser.add_argument("--max-p95-ms", type=float, default=500)
    args = parser.parse_args()
    if urlparse(args.base_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("This tool only writes synthetic fixtures to a local development server.")
    if not 0 < args.rate <= 100 or not 1 <= args.requests <= 10_000 or args.max_p95_ms <= 0:
        parser.error("Use rate (0,100], requests [1,10000], and a positive latency budget.")

    headers = {"X-Dev-Tenant-Id": "demo-tenant", "X-Dev-User-Id": "demo-inspector"}
    headers["Idempotency-Key"] = f"load-check-{uuid4()}"
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=10) as client:
        client.get("/development/demo-inspection").raise_for_status()

        def create(path: str, payload: dict) -> dict:
            response = client.post(path, json=payload)
            response.raise_for_status()
            return response.json()

        customer = create("/v1/clients", {"full_name": "Synthetic Load Test Client"})
        property_record = create("/v1/properties", {
            "address_line1": "100 Synthetic Test Street", "city": "Test City",
            "region": "ON", "postal_code": "A1A 1A1", "country": "CA",
        })
        inspection = create("/v1/inspections", {
            "client_id": customer["id"], "property_id": property_record["id"],
        })
        paths = [
            "/v1/properties?search=Synthetic&limit=20",
            f"/v1/clients/{customer['id']}/inspections?limit=20",
            f"/v1/inspections/{inspection['id']}",
            f"/v1/inspections/{inspection['id']}/media?limit=20",
        ]
        for path in paths:
            client.get(path).raise_for_status()

        def request(path: str) -> tuple[float, bool]:
            started = time.perf_counter()
            try:
                response = client.get(path)
                successful = response.status_code == 200
            except httpx.HTTPError:
                successful = False
            return (time.perf_counter() - started) * 1000, successful

        started = time.perf_counter()
        futures = []
        with ThreadPoolExecutor(max_workers=8) as executor:
            for index in range(args.requests):
                delay = started + index / args.rate - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                futures.append(executor.submit(request, paths[index % len(paths)]))
            results = [future.result() for future in futures]
        elapsed = max(time.perf_counter() - started, args.requests / args.rate)
        latencies = sorted(latency for latency, _ in results)
        failures = sum(not successful for _, successful in results)
        p95 = latencies[math.ceil(0.95 * len(latencies)) - 1]
        print(json.dumps({
            "backend": "local development; not a production database benchmark",
            "requests": len(results), "failures": failures, "target_rps": args.rate,
            "completed_rps": round(len(results) / elapsed, 2),
            "p50_ms": round(latencies[len(latencies) // 2], 2),
            "p95_ms": round(p95, 2), "max_ms": round(max(latencies), 2),
        }, indent=2))
        if failures or p95 > args.max_p95_ms or len(results) / elapsed < args.rate * 0.95:
            raise SystemExit("Directory load check did not meet its local acceptance criteria.")


if __name__ == "__main__":
    main()