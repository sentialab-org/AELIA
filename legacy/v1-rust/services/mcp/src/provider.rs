use std::collections::{BTreeMap, HashSet};
use std::net::IpAddr;
use std::sync::Arc;
use std::time::{Duration, Instant};

use anyhow::{anyhow, bail, Context};
use async_trait::async_trait;
use cognitive::DialogueToolRegistry;
use memory::graph::CognitiveGraph;
use reqwest::{redirect::Policy, Client, StatusCode};
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::{sync::Mutex, task::JoinSet};
use url::Url;

use crate::registry::{ToolDescriptor, ToolNamespace};

const SEARCH_WEB_TOOL: &str = "search.web";
const WEB_FETCH_TOOL: &str = "web.fetch";
const WEB_RETRIEVE_FAST_TOOL: &str = "web.retrieve_fast";
const BRAVE_SEARCH_API_BASE_DEFAULT: &str = "https://api.search.brave.com/res/v1/web/search";

const WEB_FETCH_TIMEOUT_MS_DEFAULT: u64 = 2_000;
const WEB_FETCH_MAX_BYTES_DEFAULT: u64 = 1_000_000;
const WEB_FETCH_MAX_CHARS_DEFAULT: usize = 20_000;
const WEB_FETCH_MAX_REDIRECTS_DEFAULT: usize = 3;
const WEB_FETCH_MAX_KEY_LINKS_DEFAULT: usize = 8;

const WEB_FETCH_TIMEOUT_MS_FLOOR: u64 = 100;
const WEB_FETCH_TIMEOUT_MS_CEILING: u64 = 20_000;
const WEB_FETCH_MAX_BYTES_FLOOR: u64 = 8_192;
const WEB_FETCH_MAX_BYTES_CEILING: u64 = 5_000_000;
const WEB_FETCH_MAX_CHARS_FLOOR: usize = 512;
const WEB_FETCH_MAX_CHARS_CEILING: usize = 200_000;
const WEB_FETCH_MAX_REDIRECTS_CEILING: usize = 10;
const WEB_FETCH_MAX_KEY_LINKS_CEILING: usize = 20;

const WEB_FETCH_ALLOWED_SCHEMES: [&str; 2] = ["http", "https"];
const WEB_FETCH_ALLOWED_CONTENT_TYPES: [&str; 3] = [
    "text/html",
    "text/plain",
    "application/xhtml+xml",
];
const WEB_FETCH_BLOCKED_SUFFIXES: [&str; 2] = [".local", ".internal"];
const WEB_FETCH_BLOCKED_HOSTS: [&str; 7] = [
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata.google.internal",
    "169.254.169.254",
    "100.100.100.200",
];
const WEB_FETCH_USER_AGENT: &str = "polyverse-agent-mcp/0.1";

const WEB_FAST_TOTAL_BUDGET_MS_DEFAULT: u64 = 1_200;
const WEB_FAST_SEARCH_TIMEOUT_MS_DEFAULT: u64 = 600;
const WEB_FAST_FETCH_TIMEOUT_MS_DEFAULT: u64 = 400;
const WEB_FAST_FETCH_K_DEFAULT: usize = 2;
const WEB_FAST_MAX_CHARS_PER_PAGE_DEFAULT: usize = 1_200;
const WEB_FAST_CACHE_TTL_MS_DEFAULT: u64 = 30_000;
const WEB_FAST_CACHE_MAX_ENTRIES_DEFAULT: usize = 128;

const WEB_FAST_TOTAL_BUDGET_MS_FLOOR: u64 = 200;
const WEB_FAST_TOTAL_BUDGET_MS_CEILING: u64 = 20_000;
const WEB_FAST_SEARCH_TIMEOUT_MS_FLOOR: u64 = 100;
const WEB_FAST_SEARCH_TIMEOUT_MS_CEILING: u64 = 5_000;
const WEB_FAST_FETCH_TIMEOUT_MS_FLOOR: u64 = 100;
const WEB_FAST_FETCH_TIMEOUT_MS_CEILING: u64 = 3_000;
const WEB_FAST_FETCH_K_CEILING: usize = 5;
const WEB_FAST_MAX_CHARS_PER_PAGE_FLOOR: usize = 256;
const WEB_FAST_MAX_CHARS_PER_PAGE_CEILING: usize = 8_000;
const WEB_FAST_CACHE_TTL_MS_CEILING: u64 = 300_000;
const WEB_FAST_CACHE_MAX_ENTRIES_CEILING: usize = 1_024;
const WEB_FAST_FETCH_MAX_REDIRECTS: usize = 2;
const WEB_FAST_FETCH_MAX_BYTES: u64 = 512_000;
const WEB_FAST_SEARCH_TOP_K: usize = 8;

#[derive(Debug, Clone)]
struct FastCacheEntry {
    expires_at: Instant,
    value: Value,
}

#[derive(Debug, Clone)]
pub struct WebRetrieveFastProviderConfig {
    pub enabled: bool,
    pub total_budget_ms: u64,
    pub search_timeout_ms: u64,
    pub fetch_timeout_ms: u64,
    pub fetch_k_default: usize,
    pub max_chars_per_page_default: usize,
    pub cache_ttl_ms: u64,
    pub cache_max_entries: usize,
}

#[derive(Debug)]
pub struct WebRetrieveFastToolProvider {
    config: WebRetrieveFastProviderConfig,
    search_config: SearchProviderConfig,
    client: Client,
    tools: Vec<RegisteredTool>,
    cache: Mutex<BTreeMap<String, FastCacheEntry>>,
}

#[derive(Debug, Clone)]
struct WebFastEvidence {
    url: String,
    final_url: String,
    title: Option<String>,
    snippet: String,
    status: u16,
    content_type: String,
    response_ms: u64,
    truncated: bool,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct WebRetrieveFastInput {
    query: String,
    #[serde(default)]
    safesearch: Option<String>,
    #[serde(default)]
    fetch_k: Option<usize>,
    #[serde(default)]
    max_chars_per_page: Option<usize>,
}

fn remaining_budget_ms(started: Instant, total_budget_ms: u64) -> u64 {
    total_budget_ms.saturating_sub(started.elapsed().as_millis() as u64)
}

fn cache_key_for_web_fast(query: &str, safesearch: &str, fetch_k: usize, max_chars_per_page: usize) -> String {
    format!("{}\u{1f}|{}\u{1f}|{}\u{1f}|{}", query, safesearch, fetch_k, max_chars_per_page)
}

fn trim_cache_to_max_entries(cache: &mut BTreeMap<String, FastCacheEntry>, max_entries: usize) {
    while cache.len() > max_entries {
        if let Some(first_key) = cache.keys().next().cloned() {
            cache.remove(&first_key);
        } else {
            break;
        }
    }
}

fn with_fast_meta_overrides(
    mut value: Value,
    response_ms: u64,
    cache_hit: bool,
    partial: bool,
    degraded_reason: Option<&str>,
) -> Value {
    if let Some(meta) = value.get_mut("meta").and_then(|v| v.as_object_mut()) {
        meta.insert("response_ms".to_string(), json!(response_ms));
        meta.insert("cache_hit".to_string(), json!(cache_hit));
        meta.insert("partial".to_string(), json!(partial));
        meta.insert("degraded_reason".to_string(), json!(degraded_reason));
    }
    value
}

fn make_web_fast_degraded_response(
    query: &str,
    results: Vec<Value>,
    evidence: Vec<Value>,
    citations: Vec<Value>,
    search_ms: u64,
    fetch_ms: u64,
    response_ms: u64,
    budget_ms: u64,
    fetch_attempted: usize,
    fetch_succeeded: usize,
    cache_hit: bool,
    degraded_reason: Option<&str>,
) -> Value {
    json!({
        "query": query,
        "results": results,
        "evidence": evidence,
        "citations": citations,
        "meta": {
            "source": "web_retrieve_fast",
            "response_ms": response_ms,
            "search_ms": search_ms,
            "fetch_ms": fetch_ms,
            "partial": degraded_reason.is_some() || fetch_succeeded < fetch_attempted,
            "degraded_reason": degraded_reason,
            "cache_hit": cache_hit,
            "budget_ms": budget_ms,
            "fetch_attempted": fetch_attempted,
            "fetch_succeeded": fetch_succeeded
        }
    })
}

async fn fetch_web_fast_evidence(
    client: Client,
    source_url: String,
    timeout_ms: u64,
    max_chars_per_page: usize,
) -> anyhow::Result<WebFastEvidence> {
    let mut current_url = parse_and_validate_web_url(&source_url)?;
    let started = Instant::now();
    let mut redirects = 0usize;

    loop {
        validate_public_url(&current_url)?;

        let response = tokio::time::timeout(
            Duration::from_millis(timeout_ms.max(1)),
            client
                .get(current_url.clone())
                .header(
                    reqwest::header::ACCEPT,
                    "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.1",
                )
                .send(),
        )
        .await
        .map_err(|_| anyhow!("web fast fetch timeout"))??;

        if response.status().is_redirection() {
            if redirects >= WEB_FAST_FETCH_MAX_REDIRECTS {
                bail!("too many redirects");
            }
            let next = redirect_target(&current_url, response.status(), response.headers())?;
            validate_public_url(&next).context("redirect target is not allowed")?;
            current_url = next;
            redirects += 1;
            continue;
        }

        if !response.status().is_success() {
            bail!("web fast fetch returned non-success status: {}", response.status());
        }

        let status = response.status();
        let content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .map(|v| v.to_ascii_lowercase())
            .unwrap_or_default();

        ensure_allowed_content_type(&content_type)?;

        let bytes = read_bounded_body(response, WEB_FAST_FETCH_MAX_BYTES).await?;
        let raw = String::from_utf8_lossy(&bytes).to_string();

        let (title, mut content) = if is_html_content_type(&content_type) {
            (extract_html_title(&raw), normalize_html_to_text(&raw))
        } else {
            (None, normalize_plain_text(&raw))
        };

        let before_chars = content.chars().count();
        let truncated = before_chars > max_chars_per_page;
        if truncated {
            content = truncate_chars(&content, max_chars_per_page);
        }

        return Ok(WebFastEvidence {
            url: source_url,
            final_url: current_url.to_string(),
            title,
            snippet: content,
            status: status.as_u16(),
            content_type,
            response_ms: started.elapsed().as_millis() as u64,
            truncated,
        });
    }
}

fn web_retrieve_fast_input_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "query": { "type": "string", "description": "Search query string." },
            "safesearch": { "type": "string", "enum": ["off", "moderate", "strict"] },
            "fetch_k": { "type": "integer", "minimum": 1, "maximum": WEB_FAST_FETCH_K_CEILING },
            "max_chars_per_page": {
                "type": "integer",
                "minimum": WEB_FAST_MAX_CHARS_PER_PAGE_FLOOR,
                "maximum": WEB_FAST_MAX_CHARS_PER_PAGE_CEILING
            }
        },
        "required": ["query"],
        "additionalProperties": false
    })
}

impl Default for WebRetrieveFastProviderConfig {
    fn default() -> Self {
        Self {
            enabled: parse_env_bool("MCP_WEB_RETRIEVE_FAST_ENABLED", false),
            total_budget_ms: parse_env_u64("MCP_WEB_FAST_TOTAL_BUDGET_MS", WEB_FAST_TOTAL_BUDGET_MS_DEFAULT)
                .clamp(WEB_FAST_TOTAL_BUDGET_MS_FLOOR, WEB_FAST_TOTAL_BUDGET_MS_CEILING),
            search_timeout_ms: parse_env_u64("MCP_WEB_FAST_SEARCH_TIMEOUT_MS", WEB_FAST_SEARCH_TIMEOUT_MS_DEFAULT)
                .clamp(WEB_FAST_SEARCH_TIMEOUT_MS_FLOOR, WEB_FAST_SEARCH_TIMEOUT_MS_CEILING),
            fetch_timeout_ms: parse_env_u64("MCP_WEB_FAST_FETCH_TIMEOUT_MS", WEB_FAST_FETCH_TIMEOUT_MS_DEFAULT)
                .clamp(WEB_FAST_FETCH_TIMEOUT_MS_FLOOR, WEB_FAST_FETCH_TIMEOUT_MS_CEILING),
            fetch_k_default: parse_env_usize("MCP_WEB_FAST_FETCH_K_DEFAULT", WEB_FAST_FETCH_K_DEFAULT)
                .clamp(1, WEB_FAST_FETCH_K_CEILING),
            max_chars_per_page_default: parse_env_usize(
                "MCP_WEB_FAST_MAX_CHARS_PER_PAGE_DEFAULT",
                WEB_FAST_MAX_CHARS_PER_PAGE_DEFAULT,
            )
            .clamp(
                WEB_FAST_MAX_CHARS_PER_PAGE_FLOOR,
                WEB_FAST_MAX_CHARS_PER_PAGE_CEILING,
            ),
            cache_ttl_ms: parse_env_u64("MCP_WEB_FAST_CACHE_TTL_MS", WEB_FAST_CACHE_TTL_MS_DEFAULT)
                .clamp(0, WEB_FAST_CACHE_TTL_MS_CEILING),
            cache_max_entries: parse_env_usize(
                "MCP_WEB_FAST_CACHE_MAX_ENTRIES",
                WEB_FAST_CACHE_MAX_ENTRIES_DEFAULT,
            )
            .clamp(1, WEB_FAST_CACHE_MAX_ENTRIES_CEILING),
        }
    }
}

impl WebRetrieveFastProviderConfig {
    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    fn effective_fetch_k(&self, requested: Option<usize>) -> usize {
        requested.unwrap_or(self.fetch_k_default).clamp(1, self.fetch_k_default)
    }

    fn effective_max_chars_per_page(&self, requested: Option<usize>) -> usize {
        requested
            .unwrap_or(self.max_chars_per_page_default)
            .clamp(WEB_FAST_MAX_CHARS_PER_PAGE_FLOOR, self.max_chars_per_page_default)
    }
}

impl Default for WebRetrieveFastToolProvider {
    fn default() -> Self {
        Self::new(WebRetrieveFastProviderConfig::default(), SearchProviderConfig::default())
    }
}

impl WebRetrieveFastToolProvider {
    pub fn new(config: WebRetrieveFastProviderConfig, search_config: SearchProviderConfig) -> Self {
        let timeout = Duration::from_millis(config.total_budget_ms.max(100));
        let client = Client::builder()
            .timeout(timeout)
            .redirect(Policy::none())
            .user_agent(WEB_FETCH_USER_AGENT)
            .build()
            .unwrap_or_else(|_| Client::new());

        let tools = if config.is_enabled() {
            vec![RegisteredTool {
                descriptor: ToolDescriptor {
                    namespace: ToolNamespace::Read,
                    name: WEB_RETRIEVE_FAST_TOOL,
                    read_only: true,
                },
                description: "Fast single-call web retrieval: search + bounded evidence fetch with strict latency budget.",
                input_schema: web_retrieve_fast_input_schema(),
            }]
        } else {
            Vec::new()
        };

        Self {
            config,
            search_config,
            client,
            tools,
            cache: Mutex::new(BTreeMap::new()),
        }
    }

    pub fn is_enabled(&self) -> bool {
        self.config.is_enabled()
    }

    async fn execute_retrieve_fast(&self, input: Value) -> anyhow::Result<Value> {
        if !self.is_enabled() {
            bail!("web retrieve fast tools are disabled");
        }

        let input: WebRetrieveFastInput = serde_json::from_value(input)?;
        let query = input.query.trim().to_string();
        if query.is_empty() {
            bail!("query is required");
        }

        let safesearch = normalize_safesearch(input.safesearch)?;
        let fetch_k = self.config.effective_fetch_k(input.fetch_k);
        let max_chars_per_page = self.config.effective_max_chars_per_page(input.max_chars_per_page);

        let cache_key = cache_key_for_web_fast(&query, &safesearch, fetch_k, max_chars_per_page);
        let started = Instant::now();

        if self.config.cache_ttl_ms > 0 {
            let mut cache = self.cache.lock().await;
            cache.retain(|_, entry| entry.expires_at > Instant::now());
            if let Some(entry) = cache.get(&cache_key) {
                return Ok(with_fast_meta_overrides(
                    entry.value.clone(),
                    started.elapsed().as_millis() as u64,
                    true,
                    entry
                        .value
                        .get("meta")
                        .and_then(|m| m.get("partial"))
                        .and_then(|v| v.as_bool())
                        .unwrap_or(false),
                    entry
                        .value
                        .get("meta")
                        .and_then(|m| m.get("degraded_reason"))
                        .and_then(|v| v.as_str()),
                ));
            }
        }

        let api_key = self
            .search_config
            .api_key
            .as_deref()
            .ok_or_else(|| anyhow!("missing BRAVE_SEARCH_API_KEY"))?;

        let search_started = Instant::now();
        let search_remaining = remaining_budget_ms(started, self.config.total_budget_ms);
        if search_remaining == 0 {
            let out = make_web_fast_degraded_response(
                &query,
                vec![],
                vec![],
                vec![],
                0,
                0,
                started.elapsed().as_millis() as u64,
                self.config.total_budget_ms,
                0,
                0,
                false,
                Some("budget_exhausted_before_search"),
            );
            return Ok(out);
        }

        let search_timeout_ms = self
            .config
            .search_timeout_ms
            .min(search_remaining)
            .max(1);
        let search_count = fetch_k.max(3).min(WEB_FAST_SEARCH_TOP_K);

        let search_response = tokio::time::timeout(
            Duration::from_millis(search_timeout_ms),
            self.client
                .get(&self.search_config.brave_api_base)
                .header("X-Subscription-Token", api_key)
                .query(&[
                    ("q", query.as_str()),
                    ("count", &search_count.to_string()),
                    ("offset", "0"),
                    ("safesearch", safesearch.as_str()),
                ])
                .send(),
        )
        .await;

        let search_payload: BraveSearchResponse = match search_response {
            Ok(Ok(resp)) => resp
                .error_for_status()
                .map_err(|err| anyhow!("brave search returned error: {err}"))?
                .json()
                .await
                .context("failed to parse brave search response")?,
            Ok(Err(_)) => {
                return Ok(make_web_fast_degraded_response(
                    &query,
                    vec![],
                    vec![],
                    vec![],
                    search_started.elapsed().as_millis() as u64,
                    0,
                    started.elapsed().as_millis() as u64,
                    self.config.total_budget_ms,
                    0,
                    0,
                    false,
                    Some("search_failed"),
                ));
            }
            Err(_) => {
                return Ok(make_web_fast_degraded_response(
                    &query,
                    vec![],
                    vec![],
                    vec![],
                    search_started.elapsed().as_millis() as u64,
                    0,
                    started.elapsed().as_millis() as u64,
                    self.config.total_budget_ms,
                    0,
                    0,
                    false,
                    Some("search_timeout"),
                ));
            }
        };

        let search_ms = search_started.elapsed().as_millis() as u64;

        let mut results = Vec::new();
        let mut citations = Vec::new();
        let mut fetch_targets = Vec::new();

        for item in search_payload
            .web
            .map(|section| section.results)
            .unwrap_or_default()
            .into_iter()
            .take(search_count)
        {
            let snippet = item
                .description
                .clone()
                .or(item.snippet.clone())
                .or_else(|| item.extra_snippets.clone().and_then(|mut xs| xs.drain(..).next()))
                .unwrap_or_default();

            results.push(json!({
                "title": item.title,
                "url": item.url,
                "snippet": snippet,
                "age": item.age,
            }));

            citations.push(json!({
                "title": item.title,
                "url": item.url,
            }));

            if fetch_targets.len() < fetch_k {
                fetch_targets.push(item.url);
            }
        }

        let fetch_started = Instant::now();
        let mut join_set = JoinSet::new();
        for url in fetch_targets.iter().cloned() {
            join_set.spawn(fetch_web_fast_evidence(
                self.client.clone(),
                url,
                self.config.fetch_timeout_ms,
                max_chars_per_page,
            ));
        }

        let mut evidence = Vec::new();
        let fetch_attempted = fetch_targets.len();
        let mut fetch_succeeded = 0usize;
        let mut degraded_reason: Option<&str> = None;

        while !join_set.is_empty() {
            if remaining_budget_ms(started, self.config.total_budget_ms) == 0 {
                join_set.abort_all();
                degraded_reason = Some("budget_exhausted_during_fetch");
                break;
            }

            match join_set.join_next().await {
                Some(Ok(Ok(item))) => {
                    fetch_succeeded += 1;
                    evidence.push(json!({
                        "url": item.url,
                        "final_url": item.final_url,
                        "title": item.title,
                        "snippet": item.snippet,
                        "status": item.status,
                        "content_type": item.content_type,
                        "response_ms": item.response_ms,
                        "truncated": item.truncated,
                    }));
                }
                Some(Ok(Err(_))) => {
                    degraded_reason.get_or_insert("partial_fetch_failed");
                }
                Some(Err(_)) => {
                    degraded_reason.get_or_insert("partial_fetch_failed");
                }
                None => break,
            }
        }

        let fetch_ms = fetch_started.elapsed().as_millis() as u64;
        let out = make_web_fast_degraded_response(
            &query,
            results,
            evidence,
            citations,
            search_ms,
            fetch_ms,
            started.elapsed().as_millis() as u64,
            self.config.total_budget_ms,
            fetch_attempted,
            fetch_succeeded,
            false,
            degraded_reason,
        );

        if self.config.cache_ttl_ms > 0 {
            let mut cache = self.cache.lock().await;
            cache.retain(|_, entry| entry.expires_at > Instant::now());
            cache.insert(
                cache_key,
                FastCacheEntry {
                    expires_at: Instant::now() + Duration::from_millis(self.config.cache_ttl_ms),
                    value: out.clone(),
                },
            );
            trim_cache_to_max_entries(&mut cache, self.config.cache_max_entries);
        }

        Ok(out)
    }
}

#[async_trait]
impl ToolProvider for WebRetrieveFastToolProvider {
    fn tools(&self) -> &[RegisteredTool] {
        &self.tools
    }

    async fn execute(
        &self,
        name: &str,
        input: Value,
        _graph: &CognitiveGraph,
    ) -> Option<anyhow::Result<Value>> {
        if name != WEB_RETRIEVE_FAST_TOOL {
            return None;
        }

        Some(self.execute_retrieve_fast(input).await)
    }
}


#[derive(Debug, Clone)]
pub struct RegisteredTool {
    pub descriptor: ToolDescriptor,
    pub description: &'static str,
    pub input_schema: Value,
}

#[async_trait]
pub trait ToolProvider: Send + Sync {
    fn tools(&self) -> &[RegisteredTool];

    async fn execute(
        &self,
        name: &str,
        input: Value,
        graph: &CognitiveGraph,
    ) -> Option<anyhow::Result<Value>>;
}

#[derive(Debug, Clone)]
pub struct SocialToolProvider {
    registry: DialogueToolRegistry,
    tools: Vec<RegisteredTool>,
}

#[derive(Debug, Clone)]
pub struct ExecutionToolProvider {
    enabled: bool,
    tools: Vec<RegisteredTool>,
}

#[derive(Debug, Clone)]
pub struct SearchProviderConfig {
    pub enabled: bool,
    pub api_key: Option<String>,
    pub timeout_ms: u64,
    pub max_results: usize,
    pub brave_api_base: String,
}

#[derive(Debug, Clone)]
pub struct SearchToolProvider {
    config: SearchProviderConfig,
    client: Client,
    tools: Vec<RegisteredTool>,
}

#[derive(Debug, Clone)]
pub struct WebFetchProviderConfig {
    pub enabled: bool,
    pub timeout_ms: u64,
    pub max_bytes: u64,
    pub max_chars: usize,
    pub max_redirects: usize,
    pub max_key_links: usize,
}

#[derive(Debug, Clone)]
pub struct WebFetchToolProvider {
    config: WebFetchProviderConfig,
    client: Client,
    tools: Vec<RegisteredTool>,
}

impl Default for SocialToolProvider {
    fn default() -> Self {
        Self {
            registry: DialogueToolRegistry::default(),
            tools: vec![
                RegisteredTool {
                    descriptor: ToolDescriptor {
                        namespace: ToolNamespace::Read,
                        name: "social.get_affect_context",
                        read_only: true,
                    },
                    description: "Read affect and relationship context for a user.",
                    input_schema: social_tool_input_schema(),
                },
                RegisteredTool {
                    descriptor: ToolDescriptor {
                        namespace: ToolNamespace::Read,
                        name: "social.get_dialogue_summary",
                        read_only: true,
                    },
                    description: "Read dialogue summary and trust/tension state for a user.",
                    input_schema: social_tool_input_schema(),
                },
            ],
        }
    }
}

#[async_trait]
impl ToolProvider for SocialToolProvider {
    fn tools(&self) -> &[RegisteredTool] {
        &self.tools
    }

    async fn execute(
        &self,
        name: &str,
        input: Value,
        graph: &CognitiveGraph,
    ) -> Option<anyhow::Result<Value>> {
        self.registry.get(name)?;
        Some(self.registry.execute(name, input, graph).await)
    }
}

impl Default for ExecutionToolProvider {
    fn default() -> Self {
        Self::new(false)
    }
}

impl ExecutionToolProvider {
    pub fn new(enabled: bool) -> Self {
        let tools = if enabled {
            vec![RegisteredTool {
                descriptor: ToolDescriptor {
                    namespace: ToolNamespace::Action,
                    name: "execution.run_shell",
                    read_only: false,
                },
                description: "Execute a shell command in the local sandbox.",
                input_schema: execution_run_shell_input_schema(),
            }]
        } else {
            Vec::new()
        };

        Self { enabled, tools }
    }

    pub fn is_enabled(&self) -> bool {
        self.enabled
    }
}

#[async_trait]
impl ToolProvider for ExecutionToolProvider {
    fn tools(&self) -> &[RegisteredTool] {
        &self.tools
    }

    async fn execute(
        &self,
        name: &str,
        _input: Value,
        _graph: &CognitiveGraph,
    ) -> Option<anyhow::Result<Value>> {
        if name != "execution.run_shell" {
            return None;
        }

        if !self.enabled {
            return Some(Err(anyhow!("execution tools are disabled")));
        }

        Some(Err(anyhow!("execution provider is not implemented yet")))
    }
}

impl Default for SearchProviderConfig {
    fn default() -> Self {
        let enabled = parse_env_bool("MCP_SEARCH_ENABLED", false);
        let api_key = parse_env_string("BRAVE_SEARCH_API_KEY");
        let timeout_ms = parse_env_u64("MCP_SEARCH_TIMEOUT_MS", 2_000).max(100);
        let max_results = parse_env_usize("MCP_SEARCH_MAX_RESULTS", 5).clamp(1, 10);
        let brave_api_base = parse_env_string("MCP_SEARCH_BRAVE_API_BASE")
            .unwrap_or_else(|| BRAVE_SEARCH_API_BASE_DEFAULT.to_string());

        Self {
            enabled,
            api_key,
            timeout_ms,
            max_results,
            brave_api_base,
        }
    }
}

impl SearchProviderConfig {
    pub fn is_enabled(&self) -> bool {
        self.enabled && self.api_key.as_deref().is_some_and(|key| !key.trim().is_empty())
    }
}

impl Default for SearchToolProvider {
    fn default() -> Self {
        Self::new(SearchProviderConfig::default())
    }
}

impl SearchToolProvider {
    pub fn new(config: SearchProviderConfig) -> Self {
        let timeout = Duration::from_millis(config.timeout_ms.max(100));
        let client = Client::builder()
            .timeout(timeout)
            .build()
            .unwrap_or_else(|_| Client::new());

        let tools = if config.is_enabled() {
            vec![RegisteredTool {
                descriptor: ToolDescriptor {
                    namespace: ToolNamespace::Read,
                    name: SEARCH_WEB_TOOL,
                    read_only: true,
                },
                description: "Search the public web and return top Brave results.",
                input_schema: search_web_input_schema(),
            }]
        } else {
            Vec::new()
        };

        Self {
            config,
            client,
            tools,
        }
    }

    pub fn is_enabled(&self) -> bool {
        self.config.is_enabled()
    }

    async fn execute_search_web(&self, input: Value) -> anyhow::Result<Value> {
        if !self.is_enabled() {
            bail!("search tools are disabled")
        }

        let input: SearchWebInput = serde_json::from_value(input)?;
        let query = input.query.trim().to_string();
        if query.is_empty() {
            bail!("query is required")
        }

        let count = input
            .count
            .unwrap_or(self.config.max_results)
            .clamp(1, self.config.max_results);
        let offset = input.offset.unwrap_or(0);
        let safesearch = normalize_safesearch(input.safesearch)?;

        let api_key = self
            .config
            .api_key
            .as_deref()
            .ok_or_else(|| anyhow!("missing BRAVE_SEARCH_API_KEY"))?;

        let started = Instant::now();
        let response = self
            .client
            .get(&self.config.brave_api_base)
            .header("X-Subscription-Token", api_key)
            .query(&[
                ("q", query.as_str()),
                ("count", &count.to_string()),
                ("offset", &offset.to_string()),
                ("safesearch", safesearch.as_str()),
            ])
            .send()
            .await
            .context("brave search request failed")?
            .error_for_status()
            .map_err(|err| anyhow!("brave search returned error: {err}"))?;

        let payload: BraveSearchResponse = response
            .json()
            .await
            .context("failed to parse brave search response")?;

        let results = payload
            .web
            .map(|section| section.results)
            .unwrap_or_default()
            .into_iter()
            .take(count)
            .map(|item| {
                let snippet = item
                    .description
                    .or(item.snippet)
                    .or_else(|| item.extra_snippets.and_then(|mut xs| xs.drain(..).next()))
                    .unwrap_or_default();

                json!({
                    "title": item.title,
                    "url": item.url,
                    "snippet": snippet,
                    "age": item.age,
                })
            })
            .collect::<Vec<_>>();

        Ok(json!({
            "query": query,
            "engine": "brave",
            "results": results,
            "meta": {
                "source": "brave_search",
                "cached": false,
                "response_ms": started.elapsed().as_millis() as u64,
            }
        }))
    }
}

#[async_trait]
impl ToolProvider for SearchToolProvider {
    fn tools(&self) -> &[RegisteredTool] {
        &self.tools
    }

    async fn execute(
        &self,
        name: &str,
        input: Value,
        _graph: &CognitiveGraph,
    ) -> Option<anyhow::Result<Value>> {
        if name != SEARCH_WEB_TOOL {
            return None;
        }

        Some(self.execute_search_web(input).await)
    }
}

impl Default for WebFetchProviderConfig {
    fn default() -> Self {
        Self {
            enabled: parse_env_bool("MCP_WEB_FETCH_ENABLED", false),
            timeout_ms: parse_env_u64("MCP_WEB_FETCH_TIMEOUT_MS", WEB_FETCH_TIMEOUT_MS_DEFAULT)
                .clamp(WEB_FETCH_TIMEOUT_MS_FLOOR, WEB_FETCH_TIMEOUT_MS_CEILING),
            max_bytes: parse_env_u64("MCP_WEB_FETCH_MAX_BYTES", WEB_FETCH_MAX_BYTES_DEFAULT)
                .clamp(WEB_FETCH_MAX_BYTES_FLOOR, WEB_FETCH_MAX_BYTES_CEILING),
            max_chars: parse_env_usize("MCP_WEB_FETCH_MAX_CHARS", WEB_FETCH_MAX_CHARS_DEFAULT)
                .clamp(WEB_FETCH_MAX_CHARS_FLOOR, WEB_FETCH_MAX_CHARS_CEILING),
            max_redirects: parse_env_usize(
                "MCP_WEB_FETCH_MAX_REDIRECTS",
                WEB_FETCH_MAX_REDIRECTS_DEFAULT,
            )
            .clamp(1, WEB_FETCH_MAX_REDIRECTS_CEILING),
            max_key_links: parse_env_usize(
                "MCP_WEB_FETCH_MAX_KEY_LINKS",
                WEB_FETCH_MAX_KEY_LINKS_DEFAULT,
            )
            .clamp(1, WEB_FETCH_MAX_KEY_LINKS_CEILING),
        }
    }
}

impl WebFetchProviderConfig {
    pub fn is_enabled(&self) -> bool {
        self.enabled
    }

    fn effective_max_chars(&self, requested: Option<usize>) -> usize {
        requested
            .unwrap_or(self.max_chars)
            .clamp(WEB_FETCH_MAX_CHARS_FLOOR, self.max_chars)
    }
}

impl Default for WebFetchToolProvider {
    fn default() -> Self {
        Self::new(WebFetchProviderConfig::default())
    }
}

impl WebFetchToolProvider {
    pub fn new(config: WebFetchProviderConfig) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_millis(config.timeout_ms))
            .redirect(Policy::none())
            .user_agent(WEB_FETCH_USER_AGENT)
            .build()
            .unwrap_or_else(|_| Client::new());

        let tools = if config.is_enabled() {
            vec![RegisteredTool {
                descriptor: ToolDescriptor {
                    namespace: ToolNamespace::Read,
                    name: WEB_FETCH_TOOL,
                    read_only: true,
                },
                description: "Fetch a public webpage URL and return bounded text content.",
                input_schema: web_fetch_input_schema(),
            }]
        } else {
            Vec::new()
        };

        Self {
            config,
            client,
            tools,
        }
    }

    pub fn is_enabled(&self) -> bool {
        self.config.is_enabled()
    }

    async fn execute_web_fetch(&self, input: Value) -> anyhow::Result<Value> {
        if !self.is_enabled() {
            bail!("web fetch tools are disabled");
        }

        let input: WebFetchInput = serde_json::from_value(input)?;
        let source_url = input.url.trim();
        if source_url.is_empty() {
            bail!("url is required");
        }

        let instruction = input.instruction.map(|v| v.trim().to_string()).filter(|v| !v.is_empty());
        let max_chars = self.config.effective_max_chars(input.max_chars);

        let mut current_url = parse_and_validate_web_url(source_url)?;
        let started = Instant::now();
        let mut redirects = 0usize;

        loop {
            validate_public_url(&current_url)?;

            let response = self
                .client
                .get(current_url.clone())
                .header(
                    reqwest::header::ACCEPT,
                    "text/html,text/plain,application/xhtml+xml;q=0.9,*/*;q=0.1",
                )
                .send()
                .await
                .context("web fetch request failed")?;

            if response.status().is_redirection() {
                if redirects >= self.config.max_redirects {
                    bail!("too many redirects");
                }
                let next = redirect_target(&current_url, response.status(), response.headers())?;
                validate_public_url(&next).context("redirect target is not allowed")?;
                current_url = next;
                redirects += 1;
                continue;
            }

            if !response.status().is_success() {
                bail!("web fetch returned non-success status: {}", response.status());
            }

            let status = response.status();
            let content_type = response
                .headers()
                .get(reqwest::header::CONTENT_TYPE)
                .and_then(|v| v.to_str().ok())
                .map(|v| v.to_ascii_lowercase())
                .unwrap_or_default();

            ensure_allowed_content_type(&content_type)?;

            let bytes = read_bounded_body(response, self.config.max_bytes).await?;
            let byte_len = bytes.len() as u64;
            let raw = String::from_utf8_lossy(&bytes).to_string();

            let (title, mut content_markdown, key_links) = if is_html_content_type(&content_type) {
                let title = extract_html_title(&raw);
                let content = normalize_html_to_text(&raw);
                let links = extract_key_links(&raw, &current_url, self.config.max_key_links);
                (title, content, links)
            } else {
                (None, normalize_plain_text(&raw), Vec::new())
            };

            let before_chars = content_markdown.chars().count();
            let truncated = before_chars > max_chars;
            if truncated {
                content_markdown = truncate_chars(&content_markdown, max_chars);
            }

            return Ok(json!({
                "url": source_url,
                "final_url": current_url.as_str(),
                "status": status.as_u16(),
                "title": title,
                "content_markdown": content_markdown,
                "key_links": key_links,
                "meta": {
                    "source": "web_fetch",
                    "engine": "generic_http",
                    "cached": false,
                    "response_ms": started.elapsed().as_millis() as u64,
                    "bytes": byte_len,
                    "content_type": content_type,
                    "redirect_count": redirects,
                    "truncated": truncated,
                    "max_chars": max_chars,
                    "instruction": instruction,
                }
            }));
        }
    }
}

#[async_trait]
impl ToolProvider for WebFetchToolProvider {
    fn tools(&self) -> &[RegisteredTool] {
        &self.tools
    }

    async fn execute(
        &self,
        name: &str,
        input: Value,
        _graph: &CognitiveGraph,
    ) -> Option<anyhow::Result<Value>> {
        if name != WEB_FETCH_TOOL {
            return None;
        }

        Some(self.execute_web_fetch(input).await)
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct SearchWebInput {
    query: String,
    #[serde(default)]
    count: Option<usize>,
    #[serde(default)]
    offset: Option<usize>,
    #[serde(default)]
    safesearch: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct WebFetchInput {
    url: String,
    #[serde(default)]
    instruction: Option<String>,
    #[serde(default)]
    max_chars: Option<usize>,
}

#[derive(Debug, Deserialize)]
struct BraveSearchResponse {
    #[serde(default)]
    web: Option<BraveWebSection>,
}

#[derive(Debug, Deserialize)]
struct BraveWebSection {
    #[serde(default)]
    results: Vec<BraveWebResult>,
}

#[derive(Debug, Deserialize)]
struct BraveWebResult {
    title: String,
    url: String,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    snippet: Option<String>,
    #[serde(default)]
    extra_snippets: Option<Vec<String>>,
    #[serde(default)]
    age: Option<String>,
}

fn parse_env_bool(name: &str, default: bool) -> bool {
    std::env::var(name)
        .ok()
        .map(|v| matches!(v.trim().to_ascii_lowercase().as_str(), "1" | "true" | "yes" | "on"))
        .unwrap_or(default)
}

fn parse_env_u64(name: &str, default: u64) -> u64 {
    std::env::var(name)
        .ok()
        .and_then(|v| v.trim().parse::<u64>().ok())
        .unwrap_or(default)
}

fn parse_env_usize(name: &str, default: usize) -> usize {
    std::env::var(name)
        .ok()
        .and_then(|v| v.trim().parse::<usize>().ok())
        .unwrap_or(default)
}

fn parse_env_string(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|v| v.trim().to_string())
        .filter(|v| !v.is_empty())
}

fn normalize_safesearch(value: Option<String>) -> anyhow::Result<String> {
    let raw = value.unwrap_or_else(|| "moderate".to_string());
    let normalized = raw.trim().to_ascii_lowercase();

    match normalized.as_str() {
        "off" | "moderate" | "strict" => Ok(normalized),
        _ => bail!("safesearch must be one of: off, moderate, strict"),
    }
}

fn social_tool_input_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "user_id": { "type": "string", "description": "User identifier to query." },
            "memory_hint": { "type": "number", "minimum": 0.0, "maximum": 1.0 },
            "max_staleness_ms": { "type": "integer", "minimum": 0 },
            "allow_stale_fallback": { "type": "boolean" },
            "force_project": { "type": "boolean" }
        },
        "required": ["user_id"],
        "additionalProperties": false
    })
}

fn execution_run_shell_input_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "command": { "type": "string", "description": "Shell command to execute." },
            "cwd": { "type": "string", "description": "Working directory override." },
            "timeout_ms": { "type": "integer", "minimum": 1 },
            "env": {
                "type": "object",
                "additionalProperties": { "type": "string" }
            }
        },
        "required": ["command"],
        "additionalProperties": false
    })
}

fn search_web_input_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "query": { "type": "string", "description": "Search query string." },
            "count": { "type": "integer", "minimum": 1, "maximum": 10 },
            "offset": { "type": "integer", "minimum": 0 },
            "safesearch": { "type": "string", "enum": ["off", "moderate", "strict"] }
        },
        "required": ["query"],
        "additionalProperties": false
    })
}

fn web_fetch_input_schema() -> Value {
    json!({
        "type": "object",
        "properties": {
            "url": { "type": "string", "description": "HTTP(S) URL to fetch." },
            "instruction": { "type": "string", "description": "Optional extraction hint." },
            "max_chars": { "type": "integer", "minimum": WEB_FETCH_MAX_CHARS_FLOOR, "maximum": WEB_FETCH_MAX_CHARS_CEILING }
        },
        "required": ["url"],
        "additionalProperties": false
    })
}

fn parse_and_validate_web_url(raw: &str) -> anyhow::Result<Url> {
    let url = Url::parse(raw).map_err(|_| anyhow!("invalid url"))?;
    validate_public_url(&url)?;
    Ok(url)
}

fn validate_public_url(url: &Url) -> anyhow::Result<()> {
    let scheme = url.scheme().to_ascii_lowercase();
    if !WEB_FETCH_ALLOWED_SCHEMES.contains(&scheme.as_str()) {
        bail!("url scheme must be http or https");
    }

    if !url.username().is_empty() || url.password().is_some() {
        bail!("url with credentials is not allowed");
    }

    let host = url.host().ok_or_else(|| anyhow!("url host is not allowed"))?;

    match host {
        url::Host::Domain(domain) => {
            let host = domain.trim_end_matches('.').to_ascii_lowercase();
            if host.is_empty() {
                bail!("url host is not allowed");
            }

            if WEB_FETCH_BLOCKED_HOSTS.contains(&host.as_str()) {
                bail!("url host is not allowed");
            }

            if WEB_FETCH_BLOCKED_SUFFIXES
                .iter()
                .any(|suffix| host.ends_with(suffix))
            {
                bail!("url host is not allowed");
            }
        }
        url::Host::Ipv4(ip4) => {
            let ip_text = ip4.to_string();
            if WEB_FETCH_BLOCKED_HOSTS.contains(&ip_text.as_str())
                || is_private_ip(IpAddr::V4(ip4))
            {
                bail!("url host is not allowed");
            }
        }
        url::Host::Ipv6(ip6) => {
            if is_private_ip(IpAddr::V6(ip6)) {
                bail!("url host is not allowed");
            }
        }
    }

    Ok(())
}

fn is_private_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(ip4) => {
            ip4.is_private()
                || ip4.is_loopback()
                || ip4.is_link_local()
                || ip4.is_broadcast()
                || ip4.is_documentation()
                || ip4.is_multicast()
                || ip4.is_unspecified()
        }
        IpAddr::V6(ip6) => {
            ip6.is_loopback()
                || ip6.is_unspecified()
                || ip6.is_unique_local()
                || ip6.is_unicast_link_local()
                || ip6.is_multicast()
                || is_documentation_ipv6(ip6)
                || ip6.to_ipv4_mapped().is_some_and(|mapped| is_private_ip(IpAddr::V4(mapped)))
        }
    }
}

fn is_documentation_ipv6(ip: std::net::Ipv6Addr) -> bool {
    // 2001:db8::/32 (RFC 3849)
    let segments = ip.segments();
    segments[0] == 0x2001 && segments[1] == 0x0db8
}

fn redirect_target(current_url: &Url, status: StatusCode, headers: &reqwest::header::HeaderMap) -> anyhow::Result<Url> {
    let location = headers
        .get(reqwest::header::LOCATION)
        .and_then(|v| v.to_str().ok())
        .ok_or_else(|| anyhow!("web fetch returned non-success status: {status}"))?;

    current_url
        .join(location)
        .map_err(|_| anyhow!("redirect target is not allowed"))
}

fn ensure_allowed_content_type(content_type: &str) -> anyhow::Result<()> {
    if content_type.is_empty() {
        return Ok(());
    }

    if WEB_FETCH_ALLOWED_CONTENT_TYPES
        .iter()
        .any(|allowed| content_type.starts_with(allowed))
    {
        Ok(())
    } else {
        bail!("content type is not supported")
    }
}

fn is_html_content_type(content_type: &str) -> bool {
    content_type.starts_with("text/html") || content_type.starts_with("application/xhtml+xml")
}

async fn read_bounded_body(mut response: reqwest::Response, max_bytes: u64) -> anyhow::Result<Vec<u8>> {
    let mut out = Vec::new();
    while let Some(chunk) = response.chunk().await.context("web fetch request failed")? {
        let next_len = out.len() + chunk.len();
        if next_len > max_bytes as usize {
            bail!("response exceeds max bytes");
        }
        out.extend_from_slice(&chunk);
    }
    Ok(out)
}

fn normalize_plain_text(input: &str) -> String {
    collapse_whitespace(input)
}

fn normalize_html_to_text(input: &str) -> String {
    let mut html = input.to_string();
    for (start, end) in [
        ("<script", "</script>"),
        ("<style", "</style>"),
        ("<noscript", "</noscript>"),
        ("<svg", "</svg>"),
    ] {
        html = remove_sections_case_insensitive(&html, start, end);
    }

    for tag in [
        "br", "p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6",
        "section", "article", "header", "footer", "main", "pre", "blockquote",
    ] {
        html = replace_tag_with_break(&html, tag, "\n");
    }
    for tag in ["ul", "ol", "table", "hr"] {
        html = replace_tag_with_break(&html, tag, "\n\n");
    }

    let stripped = strip_html_tags(&html);
    collapse_whitespace(&decode_html_entities(&stripped))
}

fn remove_sections_case_insensitive(input: &str, start_marker: &str, end_marker: &str) -> String {
    let lower = input.to_ascii_lowercase();
    let start_marker = start_marker.to_ascii_lowercase();
    let end_marker = end_marker.to_ascii_lowercase();

    let mut out = String::with_capacity(input.len());
    let mut cursor = 0usize;

    while let Some(start_pos) = lower[cursor..].find(&start_marker) {
        let start_idx = cursor + start_pos;
        out.push_str(&input[cursor..start_idx]);

        if let Some(end_pos_rel) = lower[start_idx..].find(&end_marker) {
            let end_idx = start_idx + end_pos_rel + end_marker.len();
            cursor = end_idx;
        } else {
            cursor = input.len();
            break;
        }
    }

    if cursor < input.len() {
        out.push_str(&input[cursor..]);
    }

    out
}

fn replace_tag_with_break(input: &str, tag: &str, replacement: &str) -> String {
    let mut out = input.to_string();
    out = replace_case_insensitive(&out, &format!("<{tag}"), replacement);
    out = replace_case_insensitive(&out, &format!("</{tag}"), replacement);
    out
}

fn replace_case_insensitive(input: &str, needle: &str, replacement: &str) -> String {
    let input_lower = input.to_ascii_lowercase();
    let needle_lower = needle.to_ascii_lowercase();

    let mut out = String::with_capacity(input.len());
    let mut cursor = 0usize;

    while let Some(pos_rel) = input_lower[cursor..].find(&needle_lower) {
        let pos = cursor + pos_rel;
        out.push_str(&input[cursor..pos]);
        out.push_str(replacement);
        cursor = pos + needle.len();
    }

    out.push_str(&input[cursor..]);
    out
}

fn strip_html_tags(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut in_tag = false;

    for ch in input.chars() {
        match ch {
            '<' => in_tag = true,
            '>' => in_tag = false,
            _ if !in_tag => out.push(ch),
            _ => {}
        }
    }

    out
}

fn decode_html_entities(input: &str) -> String {
    let mut out = input.to_string();
    for (entity, value) in [
        ("&nbsp;", " "),
        ("&amp;", "&"),
        ("&lt;", "<"),
        ("&gt;", ">"),
        ("&quot;", "\""),
        ("&#39;", "'"),
        ("&#x27;", "'"),
        ("&mdash;", "—"),
        ("&ndash;", "–"),
    ] {
        out = out.replace(entity, value);
    }
    out
}

fn collapse_whitespace(input: &str) -> String {
    let mut out = String::new();
    let mut last_was_space = false;

    for ch in input.chars() {
        if ch.is_whitespace() {
            if !last_was_space {
                out.push(' ');
                last_was_space = true;
            }
        } else {
            out.push(ch);
            last_was_space = false;
        }
    }

    out.trim().to_string()
}

fn extract_html_title(input: &str) -> Option<String> {
    let lower = input.to_ascii_lowercase();
    let start = lower.find("<title")?;
    let after_start = lower[start..].find('>')? + start + 1;
    let end = lower[after_start..].find("</title>")? + after_start;
    let raw = &input[after_start..end];
    let title = collapse_whitespace(&decode_html_entities(&strip_html_tags(raw)));
    if title.is_empty() {
        None
    } else {
        Some(title)
    }
}

fn extract_key_links(input: &str, base: &Url, limit: usize) -> Vec<String> {
    let mut out = Vec::new();
    let mut seen = HashSet::new();

    for attr in ["href", "src"] {
        for raw in extract_attribute_values(input, attr) {
            if out.len() >= limit {
                return out;
            }
            let normalized = raw.trim();
            if normalized.is_empty() {
                continue;
            }
            let lowered = normalized.to_ascii_lowercase();
            if lowered.starts_with("javascript:")
                || lowered.starts_with("mailto:")
                || lowered.starts_with("data:")
                || lowered.starts_with("tel:")
            {
                continue;
            }

            let resolved = match base.join(normalized) {
                Ok(url) => url,
                Err(_) => continue,
            };
            if validate_public_url(&resolved).is_err() {
                continue;
            }

            let value = resolved.to_string();
            if seen.insert(value.clone()) {
                out.push(value);
            }
        }
    }

    out
}

fn extract_attribute_values(input: &str, attr: &str) -> Vec<String> {
    let lower = input.to_ascii_lowercase();
    let needle = format!("{attr}=");
    let mut out = Vec::new();
    let mut cursor = 0usize;

    while let Some(pos_rel) = lower[cursor..].find(&needle) {
        let pos = cursor + pos_rel + needle.len();
        let bytes = input.as_bytes();
        if pos >= bytes.len() {
            break;
        }

        let quote = bytes[pos] as char;
        if quote == '"' || quote == '\'' {
            let start = pos + 1;
            let mut end = start;
            while end < bytes.len() && (bytes[end] as char) != quote {
                end += 1;
            }
            if end <= bytes.len() {
                out.push(input[start..end].to_string());
                cursor = end + 1;
                continue;
            }
            break;
        }

        let mut end = pos;
        while end < bytes.len() {
            let ch = bytes[end] as char;
            if ch.is_whitespace() || ch == '>' {
                break;
            }
            end += 1;
        }
        if end > pos {
            out.push(input[pos..end].to_string());
        }
        cursor = end + 1;
    }

    out
}

fn truncate_chars(input: &str, max_chars: usize) -> String {
    if input.chars().count() <= max_chars {
        return input.to_string();
    }

    let mut out = String::with_capacity(max_chars + 1);
    for (idx, ch) in input.chars().enumerate() {
        if idx >= max_chars {
            break;
        }
        out.push(ch);
    }
    out
}

pub fn default_providers() -> Vec<Arc<dyn ToolProvider>> {
    let search_config = SearchProviderConfig::default();
    vec![
        Arc::new(SocialToolProvider::default()),
        Arc::new(ExecutionToolProvider::default()),
        Arc::new(SearchToolProvider::new(search_config.clone())),
        Arc::new(WebFetchToolProvider::default()),
        Arc::new(WebRetrieveFastToolProvider::new(
            WebRetrieveFastProviderConfig::default(),
            search_config,
        )),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn execution_provider_is_disabled_by_default_and_registers_no_tools() {
        let provider = ExecutionToolProvider::default();
        assert!(!provider.is_enabled());
        assert!(provider.tools().is_empty());
    }

    #[test]
    fn execution_provider_registers_action_tool_when_enabled() {
        let provider = ExecutionToolProvider::new(true);
        assert!(provider.is_enabled());
        assert_eq!(provider.tools().len(), 1);
        let tool = &provider.tools()[0];
        assert_eq!(tool.descriptor.namespace, ToolNamespace::Action);
        assert_eq!(tool.descriptor.name, "execution.run_shell");
        assert!(!tool.descriptor.read_only);
    }

    #[tokio::test]
    async fn execution_provider_returns_explicit_disabled_error() {
        let provider = ExecutionToolProvider::default();
        let graph = CognitiveGraph::new("memory")
            .await
            .expect("in-memory graph should initialize");
        let result = provider
            .execute("execution.run_shell", json!({ "command": "echo hi" }), &graph)
            .await
            .expect("provider should handle execution tool name");

        let err = result.expect_err("disabled execution should return error");
        assert_eq!(err.to_string(), "execution tools are disabled");
    }

    #[test]
    fn search_provider_disabled_by_default_and_registers_no_tools() {
        let provider = SearchToolProvider::new(SearchProviderConfig {
            enabled: false,
            api_key: None,
            timeout_ms: 2_000,
            max_results: 5,
            brave_api_base: BRAVE_SEARCH_API_BASE_DEFAULT.to_string(),
        });
        assert!(!provider.is_enabled());
        assert!(provider.tools().is_empty());
    }

    #[test]
    fn search_provider_enabled_registers_read_tool() {
        let provider = SearchToolProvider::new(SearchProviderConfig {
            enabled: true,
            api_key: Some("test-key".to_string()),
            timeout_ms: 2_000,
            max_results: 5,
            brave_api_base: BRAVE_SEARCH_API_BASE_DEFAULT.to_string(),
        });
        assert!(provider.is_enabled());
        assert_eq!(provider.tools().len(), 1);
        let tool = &provider.tools()[0];
        assert_eq!(tool.descriptor.namespace, ToolNamespace::Read);
        assert_eq!(tool.descriptor.name, SEARCH_WEB_TOOL);
        assert!(tool.descriptor.read_only);
    }

    #[tokio::test]
    async fn search_provider_rejects_empty_query_before_network_call() {
        let provider = SearchToolProvider::new(SearchProviderConfig {
            enabled: true,
            api_key: Some("test-key".to_string()),
            timeout_ms: 2_000,
            max_results: 5,
            brave_api_base: BRAVE_SEARCH_API_BASE_DEFAULT.to_string(),
        });
        let graph = CognitiveGraph::new("memory")
            .await
            .expect("in-memory graph should initialize");

        let result = provider
            .execute(SEARCH_WEB_TOOL, json!({ "query": "   " }), &graph)
            .await
            .expect("provider should handle search.web");

        assert!(result.is_err());
        assert_eq!(
            result.expect_err("query should fail").to_string(),
            "query is required"
        );
    }

    #[tokio::test]
    async fn search_provider_rejects_invalid_safesearch_before_network_call() {
        let provider = SearchToolProvider::new(SearchProviderConfig {
            enabled: true,
            api_key: Some("test-key".to_string()),
            timeout_ms: 2_000,
            max_results: 5,
            brave_api_base: BRAVE_SEARCH_API_BASE_DEFAULT.to_string(),
        });
        let graph = CognitiveGraph::new("memory")
            .await
            .expect("in-memory graph should initialize");

        let result = provider
            .execute(
                SEARCH_WEB_TOOL,
                json!({ "query": "rust", "safesearch": "invalid" }),
                &graph,
            )
            .await
            .expect("provider should handle search.web");

        assert!(result.is_err());
        assert_eq!(
            result.expect_err("safesearch should fail").to_string(),
            "safesearch must be one of: off, moderate, strict"
        );
    }

    #[test]
    fn web_fetch_provider_disabled_by_default_and_registers_no_tools() {
        let provider = WebFetchToolProvider::new(WebFetchProviderConfig {
            enabled: false,
            timeout_ms: 2_000,
            max_bytes: 100_000,
            max_chars: 4_000,
            max_redirects: 3,
            max_key_links: 8,
        });
        assert!(!provider.is_enabled());
        assert!(provider.tools().is_empty());
    }

    #[test]
    fn web_fetch_provider_enabled_registers_read_tool() {
        let provider = WebFetchToolProvider::new(WebFetchProviderConfig {
            enabled: true,
            timeout_ms: 2_000,
            max_bytes: 100_000,
            max_chars: 4_000,
            max_redirects: 3,
            max_key_links: 8,
        });
        assert!(provider.is_enabled());
        assert_eq!(provider.tools().len(), 1);
        let tool = &provider.tools()[0];
        assert_eq!(tool.descriptor.namespace, ToolNamespace::Read);
        assert_eq!(tool.descriptor.name, WEB_FETCH_TOOL);
        assert!(tool.descriptor.read_only);
    }

    #[tokio::test]
    async fn web_fetch_rejects_invalid_scheme_before_network_call() {
        let provider = WebFetchToolProvider::new(WebFetchProviderConfig {
            enabled: true,
            timeout_ms: 2_000,
            max_bytes: 100_000,
            max_chars: 4_000,
            max_redirects: 3,
            max_key_links: 8,
        });
        let graph = CognitiveGraph::new("memory")
            .await
            .expect("in-memory graph should initialize");

        let result = provider
            .execute(WEB_FETCH_TOOL, json!({ "url": "file:///etc/passwd" }), &graph)
            .await
            .expect("provider should handle web.fetch");

        assert!(result.is_err());
        assert!(
            result
                .expect_err("invalid scheme should fail")
                .to_string()
                .contains("url scheme must be http or https")
        );
    }

    #[tokio::test]
    async fn web_fetch_rejects_localhost_before_network_call() {
        let provider = WebFetchToolProvider::new(WebFetchProviderConfig {
            enabled: true,
            timeout_ms: 2_000,
            max_bytes: 100_000,
            max_chars: 4_000,
            max_redirects: 3,
            max_key_links: 8,
        });
        let graph = CognitiveGraph::new("memory")
            .await
            .expect("in-memory graph should initialize");

        let result = provider
            .execute(WEB_FETCH_TOOL, json!({ "url": "http://localhost" }), &graph)
            .await
            .expect("provider should handle web.fetch");

        assert!(result.is_err());
        assert!(
            result
                .expect_err("localhost should fail")
                .to_string()
                .contains("url host is not allowed")
        );
    }
}
