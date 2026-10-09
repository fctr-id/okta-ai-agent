"""Trusted entry point for terminable local generated-code work."""
import ast
import asyncio
import json
import sys
import time

from src.core.process_runner import INPUT_LIMIT, WORKER_EVENT, WORKER_RESULT


async def execute_api_code(code, client):
    from src.utils.security_config import validate_generated_code
    if not validate_generated_code(code).is_valid:
        raise ValueError('API discovery code failed security validation')
    namespace = {'client': client, 'okta_client': client, 'asyncio': asyncio}
    tree = ast.parse(code)
    functions = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)]
    if not functions:
        raise ValueError('Generated code must define an async function')
    awaited_statements = [
        node for node in tree.body
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and any(isinstance(child, ast.Await) for child in ast.walk(node))
    ]
    if awaited_statements:
        last = awaited_statements[-1]
        if isinstance(last, ast.Assign) and isinstance(last.targets[0], ast.Name):
            result_expression = ast.Name(id=last.targets[0].id, ctx=ast.Load())
        elif isinstance(last, ast.AnnAssign) and isinstance(last.target, ast.Name):
            result_expression = ast.Name(id=last.target.id, ctx=ast.Load())
        elif isinstance(last, ast.Expr) and isinstance(last.value, ast.Await) and last is tree.body[-1]:
            tree.body.pop()
            result_expression = last.value
        else:
            raise ValueError('Use a top-level result assignment or a final await expression for the test result')
    else:
        result_expression = ast.Await(value=ast.Call(
            func=ast.Name(id=functions[0].name, ctx=ast.Load()), args=[], keywords=[]))
    tree.body.append(ast.Return(value=result_expression))
    wrapper = ast.parse('async def __exec_wrapper__():\n    pass\n')
    wrapper.body[0].body = tree.body
    exec(compile(ast.fix_missing_locations(wrapper), '<api-discovery-test>', 'exec'), namespace)
    return await namespace['__exec_wrapper__']()


async def api_worker(payload):
    from src.core.okta.client.base_okta_api_client import OktaAPIClient
    from src.core.agents.api_test_progress import DiscoveryTestClient

    def emit(kind, data):
        print(WORKER_EVENT + json.dumps({'kind': kind, 'data': data}, default=str), file=sys.stderr, flush=True)

    async def progress(data):
        emit('progress', data)

    client = OktaAPIClient()
    client.test_mode = True
    try:
        observed = DiscoveryTestClient(client, payload['endpoints'], payload['test_id'], progress,
                                       diagnostic_callback=lambda data: emit('diagnostic', data))
        return await execute_api_code(payload['code'], observed)
    finally:
        await client.close_session()


def sql_worker(payload):
    from src.core.security.sql_security_validator import validate_user_sql
    from src.core.okta.client.read_database import open_database
    query = payload['query']
    valid, message = validate_user_sql(query, 'local-sql-worker')
    if not valid:
        raise ValueError(message)
    connection = open_database()
    try:
        started = time.monotonic()
        cursor = connection.execute(query)
        columns = [description[0] for description in cursor.description] if cursor.description else []
        # Discovery is a sample even if a malformed LIMIT survives parent rewriting.
        rows = [dict(zip(columns, row)) for row in cursor.fetchmany(3)]
        return {'rows': rows, 'columns': columns,
                'execution_time_ms': int((time.monotonic() - started) * 1000)}
    finally:
        connection.close()


def main():
    data = sys.stdin.buffer.read(INPUT_LIMIT + 1)
    if len(data) > INPUT_LIMIT:
        raise ValueError('Worker input exceeds the size limit')
    payload = json.loads(data)
    mode = sys.argv[1]
    if mode == 'api':
        result = asyncio.run(api_worker(payload))
    elif mode == 'sql':
        result = sql_worker(payload)
    elif mode == 'analysis':
        from src.core.agents.result_analysis_agent import _execute_analysis_code
        result = _execute_analysis_code(**payload).model_dump(mode='json', exclude_unset=True)
    else:
        raise ValueError('Unknown execution worker mode')
    print(WORKER_RESULT + json.dumps(result, default=str), flush=True)


if __name__ == '__main__':
    main()
