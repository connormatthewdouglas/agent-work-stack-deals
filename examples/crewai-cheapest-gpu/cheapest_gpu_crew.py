"""Cheapest GPU for a described job, using CrewAI with the Lantern Works MCP server.

Starts `uvx lantern-works-deals-mcp` over stdio through crewai-tools' MCPServerAdapter.
Default (no LLM key): maps the job to a GPU with a simple VRAM rule and calls
compare_gpu_prices directly. With OPENAI_API_KEY set and --agent, a one-agent
CrewAI crew picks the GPU and calls the tools itself (untested by maintainers).

Usage: python cheapest_gpu_crew.py "fine-tune a 13B model with LoRA" [--agent]
"""
import json
import os
import sys

from crewai_tools import MCPServerAdapter
from mcp import StdioServerParameters

SERVER = StdioServerParameters(command="uvx", args=["lantern-works-deals-mcp"], env=dict(os.environ))


def pick_gpu(job: str) -> str:
    """Very rough VRAM heuristic for the no-LLM path."""
    j = job.lower()
    if any(k in j for k in ("70b", "65b", "pretrain", "full fine-tune")):
        return "H100"
    if any(k in j for k in ("13b", "30b", "34b", "fine-tune", "finetune", "lora")):
        return "A100"
    return "RTX 4090"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    job = args[0] if args else "serve a 7B chat model for a small team"
    with MCPServerAdapter(SERVER) as tools:
        print("tools:", ", ".join(sorted(t.name for t in tools)))
        if "--agent" in sys.argv and os.environ.get("OPENAI_API_KEY"):
            from crewai import Agent, Crew, Task

            analyst = Agent(role="GPU cost analyst", goal="Find the cheapest suitable GPU rental",
                            backstory="You size GPU jobs and compare published hourly prices.", tools=tools)
            task = Task(description=f"Job: {job}. Choose a GPU model with enough VRAM, call compare_gpu_prices, "
                                    "and report the cheapest option with price, provider and source_url.",
                        expected_output="GPU, provider, $/hr, source_url", agent=analyst)
            print(Crew(agents=[analyst], tasks=[task]).kickoff())
            return
        gpu = pick_gpu(job)
        tool = next(t for t in tools if t.name == "compare_gpu_prices")
        raw = tool.run(gpu=gpu, limit=3)
        data = json.loads(raw) if isinstance(raw, str) else raw
        print(f"job: {job}\ngpu: {gpu}\n{data['summary']}")
        for r in data["results"]:
            ref = "  (referral link)" if r.get("affiliate") else ""
            print(f"  #{r['rank']} {r['advertiser']} {r['gpu']} {r.get('tier')}: ${r['hourly_usd']}/hr, "
                  f"checked {r.get('checked_at')}, {r['source_url']}{ref}")


if __name__ == "__main__":
    main()
