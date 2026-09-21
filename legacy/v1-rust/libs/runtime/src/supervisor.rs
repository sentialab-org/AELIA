use std::collections::{HashMap, HashSet};
use std::time::Duration;

use anyhow::Result;
use kernel::event::{Event, SystemEvent};
use kernel::worker::Worker;
use tokio::sync::broadcast;
use tokio::task::JoinHandle;
use tracing::{error, info, warn};

use crate::event_bus::EventBus;

#[derive(Debug, Clone)]
struct WorkerStartupState {
    ready: bool,
    outcome: Option<String>,
}

impl WorkerStartupState {
    fn new() -> Self {
        Self {
            ready: false,
            outcome: None,
        }
    }
}

pub struct Supervisor {
    workers: Vec<Box<dyn Worker>>,
    handles: HashMap<String, JoinHandle<()>>,
    registered_workers: HashSet<String>,
    startup_states: HashMap<String, WorkerStartupState>,
    ready_rx: broadcast::Receiver<Event>,
    event_bus: EventBus,
}

impl Supervisor {
    pub fn new() -> Self {
        let event_bus = EventBus::new();
        let ready_rx = event_bus.broadcast_tx.subscribe();
        Self {
            workers: Vec::new(),
            handles: HashMap::new(),
            registered_workers: HashSet::new(),
            startup_states: HashMap::new(),
            ready_rx,
            event_bus,
        }
    }

    pub fn with_event_bus(event_bus: EventBus) -> Self {
        let ready_rx = event_bus.broadcast_tx.subscribe();
        Self {
            workers: Vec::new(),
            handles: HashMap::new(),
            registered_workers: HashSet::new(),
            startup_states: HashMap::new(),
            ready_rx,
            event_bus,
        }
    }

    pub fn event_bus(&self) -> &EventBus {
        &self.event_bus
    }

    pub fn event_bus_mut(&mut self) -> &mut EventBus {
        &mut self.event_bus
    }

    pub fn register<W: Worker>(&mut self, worker: W) {
        let name = worker.name().to_string();
        info!(worker = %name, "Registering worker");
        self.registered_workers.insert(name.clone());
        self.startup_states.insert(name, WorkerStartupState::new());
        self.workers.push(Box::new(worker));
    }

    pub async fn start_all(&mut self) -> Result<()> {
        info!(count = self.workers.len(), "Starting all registered workers");

        let workers = std::mem::take(&mut self.workers);

        for mut worker in workers {
            let name = worker.name().to_string();
            let ctx = self.event_bus.worker_context();

            let _ = self.event_bus.event_tx.send(Event::System(SystemEvent::WorkerStarted {
                name: name.clone(),
            }))
            .await;

            let task_name = name.clone();
            let handle = tokio::spawn(async move {
                info!(worker = %task_name, "Worker task starting");
                if let Err(e) = worker.start(ctx).await {
                    error!(worker = %task_name, error = %e, "Worker exited with error");
                } else {
                    info!(worker = %task_name, "Worker exited gracefully");
                }
            });

            self.handles.insert(name, handle);
        }

        info!(workers = self.registered_workers.len(), "All workers started");
        Ok(())
    }

    pub async fn wait_for_ready(&mut self, timeout: Duration) -> Result<()> {
        if self.registered_workers.is_empty() {
            return Ok(());
        }

        let expected = self.registered_workers.clone();
        let mut ready = HashSet::new();
        let mut rx = std::mem::replace(
            &mut self.ready_rx,
            self.event_bus.broadcast_tx.subscribe(),
        );
        let mut shutdown_rx = self.event_bus.shutdown_tx.subscribe();
        let deadline = tokio::time::sleep(timeout);
        tokio::pin!(deadline);

        let result = loop {
            if ready.len() >= expected.len() {
                break Ok(());
            }

            tokio::select! {
                _ = &mut deadline => {
                    let mut lines = Vec::new();
                    for name in &expected {
                        if ready.contains(name) {
                            continue;
                        }
                        let reason = self
                            .startup_states
                            .get(name)
                            .and_then(|state| state.outcome.as_deref())
                            .unwrap_or("no readiness signal received");
                        lines.push(format!("{name}: {reason}"));
                    }

                    if lines.is_empty() {
                        break Ok(());
                    }

                    break Err(anyhow::anyhow!("timed out waiting for workers to become ready:\nstartup check failed:\n- {}", lines.join("\n- ")));
                }
                recv = rx.recv() => {
                    match recv {
                        Ok(event) => match event {
                            Event::System(SystemEvent::WorkerReady { name }) => {
                                if expected.contains(&name) {
                                    ready.insert(name.clone());
                                    if let Some(state) = self.startup_states.get_mut(&name) {
                                        state.ready = true;
                                        state.outcome = Some("ready".to_string());
                                    }
                                }
                            }
                            Event::System(SystemEvent::WorkerStopped { name }) => {
                                if expected.contains(&name) {
                                    if let Some(state) = self.startup_states.get_mut(&name) {
                                        if !state.ready {
                                            state.outcome.get_or_insert_with(|| "stopped before ready".to_string());
                                        }
                                    }
                                }
                            }
                            Event::System(SystemEvent::WorkerError { name, error }) => {
                                if expected.contains(&name) {
                                    if let Some(state) = self.startup_states.get_mut(&name) {
                                        state.outcome = Some(format!("error: {error}"));
                                    }
                                }
                            }
                            _ => {}
                        },
                        Err(broadcast::error::RecvError::Lagged(_)) => {}
                        Err(broadcast::error::RecvError::Closed) => {
                            break Err(anyhow::anyhow!("broadcast channel closed before readiness barrier completed"));
                        }
                    }
                }
                _ = shutdown_rx.recv() => {
                    let mut lines = Vec::new();
                    for name in &expected {
                        if ready.contains(name) {
                            continue;
                        }
                        let reason = self
                            .startup_states
                            .get(name)
                            .and_then(|state| state.outcome.as_deref())
                            .unwrap_or("no readiness signal received");
                        lines.push(format!("{name}: {reason}"));
                    }

                    if lines.is_empty() {
                        break Err(anyhow::anyhow!("shutdown requested before readiness barrier completed"));
                    }

                    break Err(anyhow::anyhow!("shutdown requested before readiness barrier completed:\nstartup check failed:\n- {}", lines.join("\n- ")));
                }
            }
        };

        self.ready_rx = rx;
        result
    }

    pub async fn shutdown(&mut self) -> Result<()> {
        info!("Initiating graceful shutdown...");

        self.event_bus.signal_shutdown();

        let handles = std::mem::take(&mut self.handles);
        for (name, handle) in handles {
            info!(worker = %name, "Waiting for worker to stop...");
            match tokio::time::timeout(Duration::from_secs(10), handle).await {
                Ok(Ok(())) => info!(worker = %name, "Worker stopped"),
                Ok(Err(e)) => error!(worker = %name, error = %e, "Worker task panicked"),
                Err(_) => warn!(worker = %name, "Worker did not stop within timeout, aborting"),
            }
        }

        info!("All workers stopped. Shutdown complete.");
        Ok(())
    }

    pub fn worker_count(&self) -> usize {
        self.workers.len() + self.handles.len()
    }

    pub fn all_healthy(&self) -> bool {
        self.handles.values().all(|h| !h.is_finished())
    }
}

impl Default for Supervisor {
    fn default() -> Self {
        Self::new()
    }
}
