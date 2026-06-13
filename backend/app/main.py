"""
Nexus AI Capability Installer - FastAPI Backend
Main application entry point
"""
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from app.routers import capabilities, aws, deployment, config, installations
from app.routers import provisioning
from app.routers import health as health_router
from app.routers import auth as auth_router
from app.routers import mfa as mfa_router
from app.routers import sso as sso_router
from app.routers import setup as setup_router
from app.routers import eks as eks_router
from app.routers import discovery as discovery_router
from app.services.tinydb_state_manager import get_state_manager
from app.services.tinydb_capability_service import tinydb_capability_service
from app.services.migration_service import migration_service
from app.services.startup_manager import get_startup_manager, StartupManager
from app.utils.shutdown_handler import (
    initialize_shutdown_handler,
    register_shutdown_callback,
    ShutdownConfig
)

logger = logging.getLogger(__name__)

# Initialize graceful shutdown handler for clean process termination
_shutdown_handler = None
_startup_manager = None

# Create FastAPI app
app = FastAPI(
    title="Nexus AI Installer API",
    description="Backend API for Nexus AI Capability Installation Wizard",
    version="0.0.1"
)

# Configure CORS for Electron frontend and web browser
# Allow all localhost/127.0.0.1 origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8001",
        "http://127.0.0.1:8001",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include routers
app.include_router(capabilities.router)
app.include_router(aws.router)
app.include_router(deployment.router)
app.include_router(config.router)
app.include_router(installations.router)
app.include_router(provisioning.router)
app.include_router(health_router.router)
app.include_router(auth_router.router)
app.include_router(mfa_router.router)
app.include_router(sso_router.router)
app.include_router(setup_router.router)
app.include_router(eks_router.router)
app.include_router(discovery_router.router)


# ============================================
# Startup Component Initializers
# ============================================

def init_logging():
    """Initialize logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger.info("Logging initialized")


async def init_database():
    """Initialize TinyDB state manager."""
    logger.info("Initializing TinyDB state management...")
    db_manager = get_state_manager()
    logger.info(f"TinyDB initialized at: {db_manager.db_path}")
    
    # Always reload capabilities from JSON to ensure we have the latest data
    # This is important because capabilities.json may have been updated
    logger.info("Loading capabilities from JSON...")
    
    # Load capabilities from JSON file
    # Handle both development and PyInstaller packaged modes
    import sys
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running as PyInstaller bundle - data is in _MEIPASS
        backend_dir = Path(sys._MEIPASS)
    else:
        # Running in development mode
        backend_dir = Path(__file__).parent.parent
    
    capabilities_json = backend_dir / "capabilities" / "capabilities.json"
    logger.info(f"Looking for capabilities at: {capabilities_json}")
    
    if capabilities_json.exists():
        success = tinydb_capability_service.load_capabilities_from_json(
            str(capabilities_json)
        )
        if success:
            capabilities = tinydb_capability_service.get_all_capabilities()
            logger.info(f"Successfully loaded {len(capabilities)} capabilities from JSON")
            # Log eks_artifacts for debugging
            for cap in capabilities:
                eks_artifacts = cap.get('eks_artifacts')
                if eks_artifacts:
                    logger.info(f"Capability '{cap.get('name')}' has eks_artifacts: {eks_artifacts}")
        else:
            logger.warning("Failed to load capabilities from JSON")
    else:
        logger.warning(f"Capabilities JSON not found: {capabilities_json}")
    
    # Check for JSON state files and migrate if needed
    backend_dir = Path(__file__).parent.parent
    state_dir = backend_dir.parent / "deploy" / "state"
    
    if state_dir.exists():
        json_files = list(state_dir.glob("*.json"))
        
        if len(json_files) > 0:
            logger.info(f"Found {len(json_files)} JSON state files, running migration...")
            
            # Run migration
            stats = migration_service.migrate_deployment_states()
            logger.info(f"Migration complete: {stats}")
            
            # Archive JSON files if migration was successful
            if stats["successful"] > 0 and stats["failed"] == 0:
                logger.info("Archiving migrated JSON files...")
                migration_service.archive_json_files()
            else:
                logger.warning("Migration had errors, keeping JSON files as backup")


async def init_templates():
    """Validate CloudFormation templates on startup."""
    try:
        from app.services.template_validator import TemplateValidator
        from app.utils.resource_resolver import ResourceResolver
        
        logger.info("Validating CloudFormation templates...")
        
        # Log environment info
        env_info = ResourceResolver.get_environment_info()
        logger.info(f"Runtime environment: {env_info['environment_type']}")
        logger.info(f"Templates directory: {env_info.get('templates_dir', 'Not found')}")
        
        validator = TemplateValidator()
        
        # Validate against manifest if available
        manifest_result = validator.validate_against_manifest()
        if manifest_result.manifest_found:
            if manifest_result.success:
                logger.info(f"Template manifest validation passed: {manifest_result.templates_found}/{manifest_result.templates_in_manifest} templates verified")
            else:
                logger.warning(f"Template manifest validation issues: {manifest_result.warnings}")
                if manifest_result.missing_templates:
                    logger.warning(f"Missing templates: {manifest_result.missing_templates}")
        else:
            logger.info("Template manifest not found (expected in development mode)")
        
        # Quick validation of core templates
        template_result = validator.validate_templates(
            deploy_frontend=True,
            deploy_backend=True,
            check_integrity=False  # Skip integrity check on startup for speed
        )
        
        if template_result.success:
            logger.info(f"Template validation passed: {len(template_result.templates_checked)} templates available")
        else:
            logger.warning(f"Template validation issues: {template_result.summary}")
            for missing in template_result.missing_templates:
                logger.warning(f"  Missing: {missing.template_name} at {missing.expected_path}")
            logger.warning("Deployments may fail due to missing templates")
            
    except Exception as e:
        logger.warning(f"Template validation on startup failed: {e}")
        logger.warning("Template validation will be performed during deployment")
        # Don't raise - templates are non-critical for startup


async def init_aws_cleanup():
    """Cleanup orphaned AWS credentials on startup."""
    try:
        from app.services.aws_session_manager import aws_session_manager
        aws_session_manager.startup_cleanup(retention_hours=24)
        logger.info("AWS credential cleanup completed")
    except Exception as e:
        logger.warning(f"Credential cleanup on startup failed: {e}")
        # Don't raise - cleanup is non-critical


async def init_auth_setup():
    """Initialize authentication and create default admin if needed."""
    try:
        from app.services.initial_setup_service import get_setup_service
        setup_service = get_setup_service()
        result = setup_service.run_initial_setup()
        
        if result.get("setup_required"):
            logger.info("Initial setup completed - default admin created")
            logger.info(f"Default admin username: {result.get('username')}")
            logger.info(f"Default admin password: {result.get('default_password')}")
            logger.info("IMPORTANT: Change the default password on first login!")
        else:
            logger.info("Auth setup: Users already exist, skipping default admin creation")
    except Exception as e:
        logger.error(f"Auth setup on startup failed: {e}")
        import traceback
        logger.error(f"Auth setup traceback: {traceback.format_exc()}")
        # Re-raise to make this critical - users need to be able to login
        raise


@app.on_event("startup")
async def startup_event():
    """Initialize backend using StartupManager for ordered initialization."""
    global _shutdown_handler, _startup_manager
    
    try:
        # Set service start time for health endpoint
        health_router.set_service_start_time()
        
        # Initialize graceful shutdown handler first
        logger.info("Initializing graceful shutdown handler...")
        shutdown_config = ShutdownConfig(
            graceful_timeout_seconds=3,
            force_timeout_seconds=5,
            log_shutdown=True
        )
        _shutdown_handler = initialize_shutdown_handler(shutdown_config)
        
        # Register cleanup callbacks for graceful shutdown
        def cleanup_database():
            """Close database connections on shutdown."""
            try:
                logger.info("Closing database connections...")
                db_manager = get_state_manager()
                db_manager.close()
                logger.info("Database connections closed")
            except Exception as e:
                logger.error(f"Error closing database: {e}")
        
        def cleanup_aws_sessions():
            """Clean up AWS sessions on shutdown."""
            try:
                logger.info("Cleaning up AWS sessions...")
                from app.services.aws_session_manager import aws_session_manager
                aws_session_manager._sessions.clear()
                logger.info("AWS sessions cleaned up")
            except Exception as e:
                logger.error(f"Error cleaning up AWS sessions: {e}")
        
        register_shutdown_callback(cleanup_database, "database_cleanup")
        register_shutdown_callback(cleanup_aws_sessions, "aws_session_cleanup")
        
        logger.info("Graceful shutdown handler initialized with cleanup callbacks")
        
        # Initialize startup manager with ordered component initialization
        logger.info("Starting ordered component initialization...")
        _startup_manager = get_startup_manager({
            'component_timeout_ms': 30000,  # 30 seconds per component
            'max_retries': 3,
            'retry_delay_ms': 1000,
        })
        
        # Register components in order: logging → database → templates → routes
        _startup_manager.register_component("logging", init_logging, is_critical=True)
        _startup_manager.register_component("database", init_database, is_critical=True)
        _startup_manager.register_component("templates", init_templates, is_critical=False)
        _startup_manager.register_component("aws_cleanup", init_aws_cleanup, is_critical=False)
        _startup_manager.register_component("auth_setup", init_auth_setup, is_critical=False)
        
        # Run initialization sequence
        state = await _startup_manager.initialize_all()
        
        if state.is_ready:
            if state.is_degraded:
                logger.warning(f"Backend started in DEGRADED mode. Unavailable features: {state.degraded_features}")
            else:
                logger.info(f"Backend initialization complete in {state.total_duration_ms}ms")
        else:
            logger.error(f"Backend initialization FAILED: {state.error}")
        
    except Exception as e:
        logger.error(f"Failed to initialize backend: {str(e)}")
        # Mark startup manager as failed if it exists
        if _startup_manager:
            _startup_manager.state.is_ready = False
            _startup_manager.state.error = str(e)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    global _shutdown_handler
    
    try:
        logger.info("FastAPI shutdown event triggered...")
        
        # If shutdown handler exists and hasn't been triggered by signal,
        # manually execute cleanup callbacks
        if _shutdown_handler and not _shutdown_handler.is_shutting_down:
            logger.info("Executing graceful shutdown callbacks...")
            result = _shutdown_handler.shutdown()
            logger.info(f"Shutdown complete: {result.callbacks_executed} callbacks executed, "
                       f"{result.callbacks_failed} failed")
        else:
            # Fallback cleanup if shutdown handler not available
            logger.info("Shutting down TinyDB connections...")
            db_manager = get_state_manager()
            db_manager.close()
            logger.info("TinyDB connections closed")
        
        # Reset startup manager singleton
        StartupManager.reset_instance()
            
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")


@app.get("/")
async def root():
    """Health check endpoint"""
    manager = get_startup_manager()
    readiness = manager.get_readiness()
    
    return {
        "status": "ok" if readiness.get("ready", False) else "initializing",
        "message": "Nexus AI Installer API is running",
        "version": "1.0.0",
        "ready": readiness.get("ready", False),
        "phase": readiness.get("phase", "unknown"),
    }

# Note: The detailed /api/health endpoint is now provided by the health router
# The old health_check function is replaced by the health router endpoints

if __name__ == "__main__":
    # Run the server
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8001,
        log_level="info"
    )
