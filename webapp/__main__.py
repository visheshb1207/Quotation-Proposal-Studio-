"""python3 -m webapp -- start the local UI."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="webapp",
                                     description="Quotation Studio local UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    print(f"\n  Quotation Studio  ->  http://{args.host}:{args.port}\n")
    uvicorn.run("webapp.app:app", host=args.host, port=args.port,
                reload=args.reload)


if __name__ == "__main__":
    main()
