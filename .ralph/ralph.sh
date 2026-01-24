#!/bin/bash

# Define iteration limit to avoid infinite loops and token exhaustion
MAX_LOOPS=10
COUNTER=0

echo "🚀 Starting Ralph Loop: Janitor/DevOps Mode..."

while [ $COUNTER -lt $MAX_LOOPS ]; do
    let COUNTER=COUNTER+1
    echo "🔄 Iteration $COUNTER of $MAX_LOOPS"

    # Assemble dynamic context: Instructions + Plan + Memory + Loop Prompt
    # Note: Concatenating to ensure AI has the most up-to-date view
    cat instructions.md plan.md memory.md .ralph/PROMPT.md > .ralph/FULL_CONTEXT.md

    # Execute opencode
    # --dangerously-skip-permissions: Allows editing files and running commands without confirmation (YOLO Mode)
    # Adjust the command below according to your opencode CLI usage
    cat .ralph/FULL_CONTEXT.md | opencode --dangerously-skip-permissions

    # Check exit code. If opencode decides to stop (e.g., task done), break the loop.
    if [ $? -eq 0 ]; then
        echo "✅ Opencode finished execution successfully."
        
        # Optional: Check if there are git changes to decide whether to continue or stop
        if [ -z "$(git status --porcelain)" ]; then 
            echo "💤 No changes detected. Ending loop."
            break
        fi
    else
        echo "⚠️ Error in Opencode execution. Retrying..."
    fi

    echo "⏳ Cooling down engines (3s)..."
    sleep 3
done

echo "🛑 Loop finished."
