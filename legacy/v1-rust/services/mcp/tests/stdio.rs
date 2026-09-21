use std::sync::Arc;

use anyhow::{anyhow, Result};
use memory::graph::CognitiveGraph;
use mcp::{
    registry::ToolRegistry, stdio::serve_stdio, McpDispatcher, SearchProviderConfig,
    ToolCallExecutor, WebFetchProviderConfig, WebFetchToolProvider,
    WebRetrieveFastProviderConfig, WebRetrieveFastToolProvider,
};
use serde_json::{json, Value};
use tokio::io::{duplex, AsyncReadExt, AsyncWriteExt, BufReader};

async fn in_memory_graph() -> CognitiveGraph {
    CognitiveGraph::new("memory")
        .await
        .expect("in-memory graph should initialize")
}

async fn run_stdio_session(requests: &[Value], dispatcher: McpDispatcher) -> Result<Vec<Value>> {
    let (client_side, server_side) = duplex(8192);
    let (server_read, server_write) = tokio::io::split(server_side);
    let server =
        tokio::spawn(async move { serve_stdio(BufReader::new(server_read), server_write, dispatcher).await });

    let (mut client_read, mut client_write) = tokio::io::split(client_side);
    for request in requests {
        client_write
            .write_all(format!("{}\n", request).as_bytes())
            .await?;
    }
    client_write.shutdown().await?;

    let mut buf = Vec::new();
    client_read.read_to_end(&mut buf).await?;
    server.await??;

    let output = String::from_utf8(buf)?;
    output
        .lines()
        .filter(|line| !line.trim().is_empty())
        .map(serde_json::from_str)
        .collect::<Result<Vec<_>, _>>()
        .map_err(Into::into)
}

fn response_by_id(lines: &[Value], id: i64) -> Value {
    lines
        .iter()
        .find(|v| v.get("id").and_then(|n| n.as_i64()) == Some(id))
        .cloned()
        .expect("response id should exist")
}

fn web_fetch_registry() -> ToolRegistry {
    ToolRegistry::new(vec![Arc::new(WebFetchToolProvider::new(WebFetchProviderConfig {
        enabled: true,
        timeout_ms: 2_000,
        max_bytes: 100_000,
        max_chars: 4_000,
        max_redirects: 3,
        max_key_links: 8,
    }))])
}

fn web_fetch_dispatcher(graph: CognitiveGraph) -> McpDispatcher {
    McpDispatcher::with_executor(
        Arc::new(web_fetch_registry()),
        graph,
        2_000,
        ToolCallExecutor::new(|name, input, _graph| async move {
            if name != "web.fetch" {
                return Err(anyhow!("unknown MCP tool: {name}"));
            }
            let url = input
                .get("url")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown");
            Ok(json!({
                "url": url,
                "final_url": url,
                "status": 200,
                "title": "stub",
                "content_markdown": "stub content",
                "key_links": [],
                "meta": {
                    "source": "web_fetch",
                    "engine": "stub",
                    "cached": false,
                    "response_ms": 0,
                    "bytes": 12,
                    "content_type": "text/plain",
                    "redirect_count": 0,
                    "truncated": false,
                    "max_chars": 4000,
                    "instruction": null
                }
            }))
        }),
    )
}

fn web_retrieve_fast_registry() -> ToolRegistry {
    let search_config = SearchProviderConfig {
        enabled: true,
        api_key: Some("test-key".to_string()),
        timeout_ms: 2_000,
        max_results: 5,
        brave_api_base: "https://example.invalid/search".to_string(),
    };

    ToolRegistry::new(vec![Arc::new(WebRetrieveFastToolProvider::new(
        WebRetrieveFastProviderConfig {
            enabled: true,
            total_budget_ms: 1_200,
            search_timeout_ms: 600,
            fetch_timeout_ms: 400,
            fetch_k_default: 2,
            max_chars_per_page_default: 1_200,
            cache_ttl_ms: 30_000,
            cache_max_entries: 128,
        },
        search_config,
    ))])
}

fn web_retrieve_fast_dispatcher(graph: CognitiveGraph) -> McpDispatcher {
    McpDispatcher::with_executor(
        Arc::new(web_retrieve_fast_registry()),
        graph,
        2_000,
        ToolCallExecutor::new(|name, input, _graph| async move {
            if name != "web.retrieve_fast" {
                return Err(anyhow!("unknown MCP tool: {name}"));
            }
            let query = input
                .get("query")
                .and_then(|v| v.as_str())
                .unwrap_or_default();
            Ok(json!({
                "query": query,
                "results": [],
                "evidence": [],
                "citations": [],
                "meta": {
                    "source": "web_retrieve_fast",
                    "response_ms": 0,
                    "search_ms": 0,
                    "fetch_ms": 0,
                    "partial": false,
                    "degraded_reason": null,
                    "cache_hit": false,
                    "budget_ms": 1200,
                    "fetch_attempted": 0,
                    "fetch_succeeded": 0
                }
            }))
        }),
    )
}

fn web_retrieve_fast_live_dispatcher(graph: CognitiveGraph) -> McpDispatcher {
    McpDispatcher::new(Arc::new(web_retrieve_fast_registry()), graph, 2000)
}

fn assert_jsonrpc_error_code(lines: &[Value], id: i64, code: i64) {
    assert_eq!(
        response_by_id(lines, id)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(code)
    );
}

fn jsonrpc_error_message(lines: &[Value], id: i64) -> String {
    response_by_id(lines, id)
        .get("error")
        .and_then(|v| v.get("message"))
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string()
}

fn assert_validation_error_message(lines: &[Value], id: i64, needle: &str) {
    assert!(
        jsonrpc_error_message(lines, id).contains(needle),
        "expected id={id} error to contain: {needle}"
    );
}

fn assert_invalid_value_or_minimum_message(lines: &[Value], id: i64) {
    let msg = jsonrpc_error_message(lines, id);
    assert!(msg.contains("invalid value") || msg.contains("minimum") || msg.contains("must be >="));
}

fn extract_result_tool_names(lines: &[Value], id: i64) -> Vec<String> {
    response_by_id(lines, id)
        .get("result")
        .and_then(|v| v.get("tools"))
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|item| item.get("name").and_then(|v| v.as_str()))
                .map(str::to_string)
                .collect::<Vec<_>>()
        })
        .unwrap_or_default()
}

fn assert_web_retrieve_fast_call_success_shape(lines: &[Value], id: i64) {
    let call = response_by_id(lines, id);
    assert_eq!(
        call.get("result")
            .and_then(|v| v.get("isError"))
            .and_then(|v| v.as_bool()),
        Some(false)
    );

    let structured = call
        .get("result")
        .and_then(|v| v.get("structuredContent"))
        .expect("tools/call structuredContent should exist");

    assert!(structured.get("results").and_then(|v| v.as_array()).is_some());
    assert!(structured.get("evidence").and_then(|v| v.as_array()).is_some());
    assert!(structured.get("citations").and_then(|v| v.as_array()).is_some());

    let meta = structured.get("meta").expect("meta should exist");
    for key in [
        "source",
        "response_ms",
        "search_ms",
        "fetch_ms",
        "partial",
        "degraded_reason",
        "cache_hit",
        "budget_ms",
        "fetch_attempted",
        "fetch_succeeded",
    ] {
        assert!(meta.get(key).is_some(), "meta missing {key}");
    }
}

fn assert_web_retrieve_fast_get_shape(lines: &[Value], id: i64) {
    let get = response_by_id(lines, id);
    let tool = get
        .get("result")
        .and_then(|v| v.get("tool"))
        .expect("tools/get should include tool");
    assert_eq!(
        tool.get("name").and_then(|v| v.as_str()),
        Some("web.retrieve_fast")
    );
    assert!(tool.get("inputSchema").is_some());
}

fn assert_web_retrieve_fast_listed(lines: &[Value], id: i64) {
    let names = extract_result_tool_names(lines, id);
    assert_eq!(names, vec!["web.retrieve_fast".to_string()]);
}

fn assert_web_retrieve_fast_not_listed(lines: &[Value], id: i64) {
    let names = extract_result_tool_names(lines, id);
    assert!(!names.iter().any(|name| name == "web.retrieve_fast"));
}

fn web_retrieve_fast_registry_disabled() -> ToolRegistry {
    let search_config = SearchProviderConfig {
        enabled: false,
        api_key: None,
        timeout_ms: 2_000,
        max_results: 5,
        brave_api_base: "https://example.invalid/search".to_string(),
    };

    ToolRegistry::new(vec![Arc::new(WebRetrieveFastToolProvider::new(
        WebRetrieveFastProviderConfig {
            enabled: false,
            total_budget_ms: 1_200,
            search_timeout_ms: 600,
            fetch_timeout_ms: 400,
            fetch_k_default: 2,
            max_chars_per_page_default: 1_200,
            cache_ttl_ms: 30_000,
            cache_max_entries: 128,
        },
        search_config,
    ))])
}

fn web_retrieve_fast_disabled_dispatcher(graph: CognitiveGraph) -> McpDispatcher {
    McpDispatcher::new(Arc::new(web_retrieve_fast_registry_disabled()), graph, 2000)
}

fn assert_web_retrieve_fast_disabled_error(lines: &[Value], id: i64) {
    assert_jsonrpc_error_code(lines, id, -32601);
}

fn assert_web_retrieve_fast_unknown_get_error(lines: &[Value], id: i64) {
    assert_jsonrpc_error_code(lines, id, -32601);
}

fn assert_web_retrieve_fast_missing_name_get_error(lines: &[Value], id: i64) {
    assert_jsonrpc_error_code(lines, id, -32602);
}

fn assert_web_retrieve_fast_unknown_call_error(lines: &[Value], id: i64) {
    assert_jsonrpc_error_code(lines, id, -32601);
}

fn assert_web_retrieve_fast_validation_error_code(lines: &[Value], id: i64) {
    assert_jsonrpc_error_code(lines, id, -32602);
}

fn assert_web_retrieve_fast_validation_errors(lines: &[Value]) {
    for id in [13, 14, 15, 16, 17, 19] {
        assert_web_retrieve_fast_validation_error_code(lines, id);
    }
    assert_web_retrieve_fast_validation_error_code(lines, 18);

    assert_validation_error_message(lines, 13, "missing field `query`");
    assert_validation_error_message(lines, 14, "query is required");
    assert_validation_error_message(lines, 15, "safesearch must be one of: off, moderate, strict");
    assert_validation_error_message(lines, 16, "unknown field `unexpected`");
    assert_validation_error_message(lines, 17, "invalid type");
    assert_invalid_value_or_minimum_message(lines, 18);
    assert_validation_error_message(lines, 19, "arguments must be a JSON object");
}

fn assert_web_retrieve_fast_validation_and_unknown_errors(lines: &[Value]) {
    assert_web_retrieve_fast_unknown_get_error(lines, 10);
    assert_web_retrieve_fast_missing_name_get_error(lines, 11);
    assert_web_retrieve_fast_unknown_call_error(lines, 12);
    assert_web_retrieve_fast_validation_errors(lines);
}

fn assert_web_retrieve_fast_disabled_list_and_call(lines: &[Value]) {
    assert_web_retrieve_fast_not_listed(lines, 2);
    assert_web_retrieve_fast_disabled_error(lines, 3);
}

fn assert_web_retrieve_fast_success_contract(lines: &[Value]) {
    assert_web_retrieve_fast_listed(lines, 2);
    assert_web_retrieve_fast_get_shape(lines, 3);
    assert_web_retrieve_fast_call_success_shape(lines, 4);
}

fn assert_web_retrieve_fast_validation_contract(lines: &[Value]) {
    assert_web_retrieve_fast_validation_and_unknown_errors(lines);
}

fn assert_web_retrieve_fast_disabled_contract(lines: &[Value]) {
    assert_web_retrieve_fast_disabled_list_and_call(lines);
}

fn assert_web_retrieve_fast_contract(lines: &[Value]) {
    assert_web_retrieve_fast_success_contract(lines);
}

fn assert_web_retrieve_fast_error_contract(lines: &[Value]) {
    assert_web_retrieve_fast_validation_contract(lines);
}

fn assert_web_retrieve_fast_off_contract(lines: &[Value]) {
    assert_web_retrieve_fast_disabled_contract(lines);
}
#[tokio::test]
async fn stdio_server_supports_initialize_ping_list_resources_prompts_and_call() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = McpDispatcher::new(Arc::new(ToolRegistry::default()), graph, 2000);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"ping","params":{}}),
            json!({"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}),
            json!({"jsonrpc":"2.0","id":4,"method":"tools/get","params":{"name":"social.get_affect_context"}}),
            json!({"jsonrpc":"2.0","id":5,"method":"resources/list","params":{}}),
            json!({"jsonrpc":"2.0","id":6,"method":"prompts/list","params":{}}),
            json!({"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"social.get_affect_context","arguments":{"user_id":"alice","memory_hint":0.2}}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 7);

    let init = response_by_id(&lines, 1);
    assert_eq!(
        init.get("result")
            .and_then(|v| v.get("protocolVersion"))
            .and_then(|v| v.as_str()),
        Some("2025-03-26")
    );
    assert_eq!(
        init.get("result")
            .and_then(|v| v.get("capabilities"))
            .and_then(|v| v.get("tools"))
            .and_then(|v| v.get("get"))
            .and_then(|v| v.as_bool()),
        Some(true)
    );
    assert_eq!(
        init.get("result")
            .and_then(|v| v.get("capabilities"))
            .and_then(|v| v.get("tools"))
            .and_then(|v| v.get("supportsExecution"))
            .and_then(|v| v.as_bool()),
        Some(false)
    );

    let ping = response_by_id(&lines, 2);
    assert_eq!(
        ping.get("result").and_then(|v| v.as_object()).map(|v| v.len()),
        Some(0)
    );

    let list = response_by_id(&lines, 3);
    assert_eq!(
        list.get("result")
            .and_then(|v| v.get("tools"))
            .and_then(|v| v.as_array())
            .map(|arr| arr.len()),
        Some(2)
    );

    let get_tool = response_by_id(&lines, 4);
    assert_eq!(
        get_tool
            .get("result")
            .and_then(|v| v.get("tool"))
            .and_then(|v| v.get("name"))
            .and_then(|v| v.as_str()),
        Some("social.get_affect_context")
    );

    let resources = response_by_id(&lines, 5);
    assert_eq!(
        resources
            .get("result")
            .and_then(|v| v.get("resources"))
            .and_then(|v| v.as_array())
            .map(|arr| arr.len()),
        Some(0)
    );

    let prompts = response_by_id(&lines, 6);
    assert_eq!(
        prompts
            .get("result")
            .and_then(|v| v.get("prompts"))
            .and_then(|v| v.as_array())
            .map(|arr| arr.len()),
        Some(0)
    );

    let call = response_by_id(&lines, 7);
    assert_eq!(
        call.get("result")
            .and_then(|v| v.get("isError"))
            .and_then(|v| v.as_bool()),
        Some(false)
    );

    Ok(())
}

#[tokio::test]
async fn stdio_server_returns_json_rpc_errors_for_bad_calls() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = McpDispatcher::new(Arc::new(ToolRegistry::default()), graph, 2000);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":7,"method":"tools/list","params":{}}),
            json!({"jsonrpc":"2.0","id":8,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":"social.get_dialogue_summary","arguments":{}}}),
            json!({"jsonrpc":"2.0","id":10,"method":"tools/call","params":{"name":"social.unknown","arguments":{"user_id":"alice"}}}),
            json!({"jsonrpc":"2.0","id":15,"method":"tools/get","params":{"name":"social.unknown"}}),
            json!({"jsonrpc":"2.0","id":16,"method":"tools/get","params":{}}),
            json!({"jsonrpc":"2.0","id":17,"method":"tools/call","params":{"name":"social.unknown","arguments":{}}}),
            json!({"jsonrpc":"2.0","id":18,"method":"tools/call","params":{"name":"social.get_dialogue_summary","arguments":{"user_id":"alice","unexpected":true}}}),
            json!({"jsonrpc":"2.0","id":19,"method":"tools/call","params":{"name":"social.get_dialogue_summary","arguments":"oops"}}),
            json!({"jsonrpc":"2.0","id":11,"method":"logging/setLevel","params":{"level":"verbose"}}),
            json!({"jsonrpc":"2.0","id":12,"method":"ping","params":123}),
            json!({"jsonrpc":"2.0","id":13,"method":"nope.method","params":{}}),
            json!({"jsonrpc":"2.0","id":14,"method":"initialize","params":{}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(
        response_by_id(&lines, 7)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32002)
    );
    assert_eq!(
        response_by_id(&lines, 9)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32602)
    );
    assert_eq!(
        response_by_id(&lines, 10)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32601)
    );
    assert_eq!(
        response_by_id(&lines, 15)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32601)
    );
    assert_eq!(
        response_by_id(&lines, 16)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32602)
    );
    assert_eq!(
        response_by_id(&lines, 17)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32601)
    );
    assert_eq!(
        response_by_id(&lines, 18)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32602)
    );
    assert_eq!(
        response_by_id(&lines, 19)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32602)
    );
    assert_eq!(
        response_by_id(&lines, 11)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32602)
    );
    assert_eq!(
        response_by_id(&lines, 12)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32602)
    );
    assert_eq!(
        response_by_id(&lines, 13)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32601)
    );
    assert_eq!(
        response_by_id(&lines, 14)
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32003)
    );

    Ok(())
}

#[tokio::test]
async fn stdio_server_rejects_invalid_jsonrpc_and_invalid_request_shape() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = McpDispatcher::new(Arc::new(ToolRegistry::default()), graph, 2000);

    let lines = run_stdio_session(
        &[
            json!("not-json"),
            json!([1, 2, 3]),
            json!({"jsonrpc":"1.0","id":1,"method":"initialize","params":{}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 3);
    for payload in lines {
        assert!(payload.get("error").is_some());
    }

    Ok(())
}

#[tokio::test]
async fn stdio_server_handles_notifications_without_response() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = McpDispatcher::new(Arc::new(ToolRegistry::default()), graph, 2000);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","method":"tools/list","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"ping","params":{}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 2);
    assert!(lines.iter().any(|v| v.get("id").and_then(|n| n.as_i64()) == Some(1)));
    assert!(lines.iter().any(|v| v.get("id").and_then(|n| n.as_i64()) == Some(2)));

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_fetch_list_get_and_call_shapes() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_fetch_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}),
            json!({"jsonrpc":"2.0","id":3,"method":"tools/get","params":{"name":"web.fetch"}}),
            json!({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"web.fetch","arguments":{"url":"https://example.com"}}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 4);

    let list = response_by_id(&lines, 2);
    let tools = list
        .get("result")
        .and_then(|v| v.get("tools"))
        .and_then(|v| v.as_array())
        .expect("tools/list result.tools should be array");
    assert_eq!(tools.len(), 1);
    assert_eq!(
        tools[0].get("name").and_then(|v| v.as_str()),
        Some("web.fetch")
    );

    let get = response_by_id(&lines, 3);
    let tool = get
        .get("result")
        .and_then(|v| v.get("tool"))
        .expect("tools/get should include tool");
    assert_eq!(tool.get("name").and_then(|v| v.as_str()), Some("web.fetch"));
    assert!(tool.get("inputSchema").is_some());

    let call = response_by_id(&lines, 4);
    assert_eq!(
        call.get("result")
            .and_then(|v| v.get("isError"))
            .and_then(|v| v.as_bool()),
        Some(false)
    );
    let structured = call
        .get("result")
        .and_then(|v| v.get("structuredContent"))
        .expect("tools/call structuredContent should exist");
    assert_eq!(
        structured.get("status").and_then(|v| v.as_i64()),
        Some(200)
    );
    assert!(structured.get("content_markdown").and_then(|v| v.as_str()).is_some());
    assert!(structured.get("meta").and_then(|v| v.as_object()).is_some());

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_fetch_validation_and_unknown_tool_errors() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = McpDispatcher::new(Arc::new(web_fetch_registry()), graph, 2000);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":10,"method":"tools/get","params":{"name":"web.unknown"}}),
            json!({"jsonrpc":"2.0","id":11,"method":"tools/get","params":{}}),
            json!({"jsonrpc":"2.0","id":12,"method":"tools/call","params":{"name":"web.unknown","arguments":{"url":"https://example.com"}}}),
            json!({"jsonrpc":"2.0","id":13,"method":"tools/call","params":{"name":"web.fetch","arguments":{}}}),
            json!({"jsonrpc":"2.0","id":14,"method":"tools/call","params":{"name":"web.fetch","arguments":{"url":"file:///etc/passwd"}}}),
            json!({"jsonrpc":"2.0","id":15,"method":"tools/call","params":{"name":"web.fetch","arguments":{"url":"http://localhost"}}}),
            json!({"jsonrpc":"2.0","id":16,"method":"tools/call","params":{"name":"web.fetch","arguments":{"url":"https://example.com","unexpected":true}}}),
            json!({"jsonrpc":"2.0","id":17,"method":"tools/call","params":{"name":"web.fetch","arguments":{"url":"https://example.com","max_chars":"oops"}}}),
            json!({"jsonrpc":"2.0","id":18,"method":"tools/call","params":{"name":"web.fetch","arguments":{"url":"https://example.com","max_chars":-1}}}),
            json!({"jsonrpc":"2.0","id":19,"method":"tools/call","params":{"name":"web.fetch","arguments":"oops"}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 11);

    let unknown_get = response_by_id(&lines, 10);
    assert_eq!(
        unknown_get
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32601)
    );

    let missing_name_get = response_by_id(&lines, 11);
    assert_eq!(
        missing_name_get
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32602)
    );

    let unknown_call = response_by_id(&lines, 12);
    assert_eq!(
        unknown_call
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32601)
    );

    for id in [13, 14, 15, 16, 17, 19] {
        assert_eq!(
            response_by_id(&lines, id)
                .get("error")
                .and_then(|v| v.get("code"))
                .and_then(|v| v.as_i64()),
            Some(-32602)
        );
    }

    let id18 = response_by_id(&lines, 18);
    assert_eq!(
        id18
            .get("error")
            .and_then(|v| v.get("code"))
            .and_then(|v| v.as_i64()),
        Some(-32602)
    );

    assert!(
        response_by_id(&lines, 13)
            .get("error")
            .and_then(|v| v.get("message"))
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .contains("missing field `url`")
    );
    assert!(
        response_by_id(&lines, 14)
            .get("error")
            .and_then(|v| v.get("message"))
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .contains("url scheme must be http or https")
    );
    assert!(
        response_by_id(&lines, 15)
            .get("error")
            .and_then(|v| v.get("message"))
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .contains("url host is not allowed")
    );
    assert!(
        response_by_id(&lines, 16)
            .get("error")
            .and_then(|v| v.get("message"))
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .contains("unknown field `unexpected`")
    );
    assert!(
        response_by_id(&lines, 17)
            .get("error")
            .and_then(|v| v.get("message"))
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .contains("invalid type")
    );
    let id18_msg = response_by_id(&lines, 18)
        .get("error")
        .and_then(|v| v.get("message"))
        .and_then(|v| v.as_str())
        .unwrap_or_default()
        .to_string();
    assert!(
        id18_msg.contains("invalid value")
            || id18_msg.contains("minimum")
            || id18_msg.contains("must be >=")
    );
    assert!(
        response_by_id(&lines, 19)
            .get("error")
            .and_then(|v| v.get("message"))
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .contains("arguments must be a JSON object")
    );

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_retrieve_fast_list_get_and_call_shapes() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_retrieve_fast_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}),
            json!({"jsonrpc":"2.0","id":3,"method":"tools/get","params":{"name":"web.retrieve_fast"}}),
            json!({"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":{"query":"rust async runtime"}}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 4);
    assert_web_retrieve_fast_contract(&lines);

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_retrieve_fast_validation_and_unknown_tool_errors() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_retrieve_fast_live_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":10,"method":"tools/get","params":{"name":"web.unknown"}}),
            json!({"jsonrpc":"2.0","id":11,"method":"tools/get","params":{}}),
            json!({"jsonrpc":"2.0","id":12,"method":"tools/call","params":{"name":"web.unknown","arguments":{"query":"rust"}}}),
            json!({"jsonrpc":"2.0","id":13,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":{}}}),
            json!({"jsonrpc":"2.0","id":14,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":{"query":"   "}}}),
            json!({"jsonrpc":"2.0","id":15,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":{"query":"rust","safesearch":"invalid"}}}),
            json!({"jsonrpc":"2.0","id":16,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":{"query":"rust","unexpected":true}}}),
            json!({"jsonrpc":"2.0","id":17,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":{"query":"rust","fetch_k":"oops"}}}),
            json!({"jsonrpc":"2.0","id":18,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":{"query":"rust","fetch_k":-1}}}),
            json!({"jsonrpc":"2.0","id":19,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":"oops"}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 11);
    assert_web_retrieve_fast_error_contract(&lines);

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_retrieve_fast_disabled_registry_hides_tool_and_rejects_call() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_retrieve_fast_disabled_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}),
            json!({"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":{"query":"rust"}}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 3);
    assert_web_retrieve_fast_off_contract(&lines);

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_retrieve_fast_accepts_argument_alias_input() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_retrieve_fast_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"web.retrieve_fast","input":{"query":"input alias works"}}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 2);
    assert_web_retrieve_fast_call_success_shape(&lines, 2);

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_retrieve_fast_requires_object_arguments() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_retrieve_fast_live_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"web.retrieve_fast","arguments":[1,2,3]}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 2);
    assert_web_retrieve_fast_validation_error_code(&lines, 2);
    assert_validation_error_message(&lines, 2, "arguments must be a JSON object");

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_retrieve_fast_rejects_missing_tool_name_on_get() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_retrieve_fast_live_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"tools/get","params":{}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 2);
    assert_web_retrieve_fast_missing_name_get_error(&lines, 2);

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_retrieve_fast_rejects_unknown_tool_on_get() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_retrieve_fast_live_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"tools/get","params":{"name":"web.unknown"}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 2);
    assert_web_retrieve_fast_unknown_get_error(&lines, 2);

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_retrieve_fast_rejects_unknown_tool_on_call() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_retrieve_fast_live_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"web.unknown","arguments":{"query":"rust"}}}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 2);
    assert_web_retrieve_fast_unknown_call_error(&lines, 2);

    Ok(())
}

#[tokio::test]
async fn stdio_server_web_retrieve_fast_rejects_invalid_jsonrpc_shape() -> Result<()> {
    let graph = in_memory_graph().await;
    let dispatcher = web_retrieve_fast_live_dispatcher(graph);

    let lines = run_stdio_session(
        &[
            json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}),
            json!({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}),
            json!({"jsonrpc":"2.0","id":2,"method":"tools/call","params":[1,2,3]}),
        ],
        dispatcher,
    )
    .await?;

    assert_eq!(lines.len(), 2);
    assert_jsonrpc_error_code(&lines, 2, -32602);

    Ok(())
}