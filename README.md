# chuk-a2a

**In‑memory FSM for the A2A Protocol with Pydantic v2 models**

This project provides:

- **Pydantic v2 models** generated from a JSON Schema (A2A Protocol spec) with enhanced handling of `null` and union types.
- A **schema patcher** to convert `const: null` entries to `type: "null"` for compatibility with `datamodel-code-generator`.
- A **post-processor** to fix generated Pydantic models, ensuring nullable fields and union types are correctly annotated.
- An **in‑memory `TaskManager`** implementing the A2A task lifecycle as a finite state machine (FSM).
- A **CLI helper** via `Makefile` and `pdm` scripts for code generation, testing, linting, and packaging.

---

## Features

- **Automated model generation**: Use `datamodel-code-generator` to produce Pydantic v2 models from JSON Schema.
- **Null-const patching**: `fix_null_const.py` replaces any `const: null` definitions with `type: "null"`.
- **Post-processing**: `fix_pydantic_generator.py` updates unions and nullable fields for smooth Pydantic validation.
- **TaskManager FSM**: Create, update, cancel tasks; manage state transitions (`submitted`, `working`, `completed`, etc.);
  store history and artifacts in-memory with thread-safe access.
- **Test suite**: `pytest` and `pytest-asyncio` for asynchronous tests of the TaskManager.

## Getting Started

### Prerequisites

- Python **3.11**+ installed
- [pdm](https://pdm.fming.dev/) (recommended) or `pip`/`venv`

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/chuk-a2a.git
cd chuk-a2a

# Install dependencies (with pdm)
pdm install
# Or via pip in a virtualenv
pip install -e .
pip install -r requirements.txt
```

## Generating Pydantic Models

Whenever the JSON Schema (`spec/a2a_spec.json`) changes, regenerate the models:

```bash
# Using Makefile
generate-models
# Or with pdm script
pdm run generate-models
```

This runs:

1. **fix_null_const.py** to patch `const: null` entries → `spec/a2a_spec_fixed.json`
2. `datamodel-code-generator` to emit initial models → `src/a2a/models.py.temp`
3. **fix_pydantic_generator.py** to post-process unions & nullable fields → `src/a2a/models.py`
4. Cleanup temporary files

## Usage

### Importing Models

```python
from a2a.models import Task, TaskState, Message, TextPart, Artifact
```

### TaskManager Example

```python
import asyncio
from a2a.task_manager import TaskManager, InvalidTransition
from a2a.models import Message, TextPart, TaskState

async def main():
    tm = TaskManager()
    user_txt = TextPart(type="text", text="Process my data")
    msg = Message(role="user", parts=[user_txt])

    # Create a new task
    task = await tm.create_task(msg)
    print("Created task:", task.id)

    # Transition to working
    await tm.update_status(task.id, TaskState.working)

    # Add an artifact
    from a2a.models import Artifact
    result_part = TextPart(type="text", text="Here is the result")
    artifact = Artifact(name="result", parts=[result_part], index=0)
    await tm.add_artifact(task.id, artifact)

    # Complete the task
    await tm.update_status(task.id, TaskState.completed)

    print("Final state:", (await tm.get_task(task.id)).status.state)

asyncio.run(main())
```

## Testing

Run the test suite with:

```bash
# With pdm
pdm run test
# Or pytest directly
pytest
```

## Linting & Formatting

- **Format**: `make format` or `pdm run black src tests`
- **Lint**: `make lint` or `pdm run flake8 src tests`

## Building & Distribution

Create source and wheel distributions:

```bash
make build
# or
pdm build
```

## Contributing

1. Fork the repo and create a feature branch
2. Write code, tests, and documentation
3. Ensure all tests pass and linting is clean
4. Submit a Pull Request

## License

This project is licensed under the [MIT License](LICENSE).

