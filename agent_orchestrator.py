import json, os, pyautogui
from typing import TypedDict, List
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from vector_store import query_similar_workflows

# --- STATE SCHEMA ---
class AgentState(TypedDict):
    user_intent: str
    retrieved_context: str
    action_plan: List[dict]
    execution_logs: List[str]

# --- TOOL EXECUTORS ---
def execute_os_action(action: dict) -> str:
    """Executes atomic system actions based on the agent's plan."""
    action_type = action.get("type")
    
    try:
        if action_type == "open_app":
            app_name = action.get("target")
            pyautogui.press('win')  # Win key search
            pyautogui.write(app_name, interval=0.1)
            pyautogui.press('enter')
            return f"Executed: Launched '{app_name}'"
            
        elif action_type == "key_press":
            key = action.get("target")
            pyautogui.press(key)
            return f"Executed: Pressed key '{key}'"
            
        elif action_type == "click":
            pos = action.get("position", [500, 500])
            pyautogui.click(x=pos[0], y=pos[1])
            return f"Executed: Clicked at position {pos}"
            
        elif action_type == "set_volume":
            val = action.get("value", 50)
            from daemon import set_system_volume
            set_system_volume(val)
            return f"Executed: Set volume to {val}%"

        else:
            return f"Skipped unknown action type: {action_type}"
            
    except Exception as e:
        return f"Error executing action {action}: {e}"

# --- LANGGRAPH NODE FUNCTIONS ---

def retrieve_context_node(state: AgentState) -> AgentState:
    """Node 1: Retrieves similar past workflow traces from LanceDB."""
    intent = state["user_intent"]
    print(f"\n[Node: Retrieve Context] Searching LanceDB for intent: '{intent}'...")
    
    docs = query_similar_workflows(intent, k=2)
    context_text = "\n---\n".join([d.page_content for d in docs]) if docs else "No matching traces."
    
    return {
        **state,
        "retrieved_context": context_text,
        "execution_logs": state.get("execution_logs", []) + ["Retrieved past workflow contexts from LanceDB."]
    }

def synthesize_plan_node(state: AgentState) -> AgentState:
    """Node 2: Generates a structured JSON action plan using context."""
    print("\n[Node: Synthesize Plan] Generating step-by-step automation plan...")
    
    prompt = f"""
    You are an autonomous OS assistant.
    User Intent: "{state['user_intent']}"
    
    Past Observed Workflow Contexts:
    {state['retrieved_context']}
    
    Generate a JSON list of structured OS actions to satisfy the user intent.
    Supported action types: "open_app", "key_press", "click", "set_volume".
    
    Output JSON ONLY in this format:
    [
      {{"type": "open_app", "target": "spotify"}},
      {{"type": "set_volume", "value": 40}}
    ]
    """
    
    # Mock LLM response parsing (or swap with Ollama / OpenAI call)
    # Here we parse structured output for execution
    if "spotify" in state['user_intent'].lower() or "music" in state['user_intent'].lower():
        plan = [
            {"type": "open_app", "target": "spotify"},
            {"type": "set_volume", "value": 50}
        ]
    else:
        plan = [
            {"type": "set_volume", "value": 30}
        ]

    return {
        **state,
        "action_plan": plan,
        "execution_logs": state["execution_logs"] + [f"Synthesized action plan with {len(plan)} steps."]
    }

def execute_plan_node(state: AgentState) -> AgentState:
    """Node 3: Executes the synthesized actions sequentially."""
    print("\n[Node: Execute Plan] Executing OS automation actions...")
    logs = state["execution_logs"]
    
    for action in state["action_plan"]:
        result = execute_os_action(action)
        print(f"   {result}")
        logs.append(result)

    return {
        **state,
        "execution_logs": logs
    }

# --- BUILD LANGGRAPH WORKFLOW ---
workflow = StateGraph(AgentState)

# Add Nodes
workflow.add_node("retrieve_context", retrieve_context_node)
workflow.add_node("synthesize_plan", synthesize_plan_node)
workflow.add_node("execute_plan", execute_plan_node)

# Add Graph Edges
workflow.set_entry_point("retrieve_context")
workflow.add_edge("retrieve_context", "synthesize_plan")
workflow.add_edge("synthesize_plan", "execute_plan")
workflow.add_edge("execute_plan", END)

# Compile LangGraph State Machine
app_agent = workflow.compile()

# --- ENTRY POINT ---
def run_autonomous_agent(user_command: str):
    initial_state = {
        "user_intent": user_command,
        "retrieved_context": "",
        "action_plan": [],
        "execution_logs": []
    }
    
    final_state = app_agent.invoke(initial_state)
    print("\n Worklow Orchestration Complete!")
    print("Execution Log:")
    for log in final_state["execution_logs"]:
        print(f"  - {log}")

if __name__ == "__main__":
    run_autonomous_agent("Open my music and set volume to 50%")