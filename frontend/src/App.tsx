/**
 * Main Application Component
 * 
 * Integrates startup health check with loading screen.
 * Shows loading state until backend is ready.
 * Includes authentication routing.
 * 
 * Feature: startup-health-check, user-authentication
 * Requirements: 1.1, 1.4, 2.2, 3.1, 3.4, 3.5, 4.4, 4.5
 */
import { useState, useEffect, useCallback } from 'react'
import { HashRouter, BrowserRouter, Routes, Route } from 'react-router-dom'
import { WizardProvider } from './context/WizardContext'
import WizardShell from './components/WizardShell'
import LoadingScreen, { StartupStatus } from './components/LoadingScreen'
import { Login, MFAVerify, SSOCallback, ProtectedRoute, ChangePassword } from './components/auth'
import { healthApi } from './services/api'
import { defaultHealthMonitor } from './services/health-monitor'
import './App.css'

// Feature flag for authentication (enabled by default, set VITE_AUTH_ENABLED=false to disable)
// @ts-ignore - Vite env types
const AUTH_ENABLED = (import.meta as any).env?.VITE_AUTH_ENABLED !== 'false';

// Use HashRouter for Electron (file:// protocol), BrowserRouter for web
const isElectron = !!(window as any).electronAPI?.isElectron;
const Router = isElectron ? HashRouter : BrowserRouter;

const MAX_STARTUP_RETRIES = 30;  // 30 seconds total
const STARTUP_POLL_INTERVAL_MS = 1000;

function App() {
  const [startupStatus, setStartupStatus] = useState<StartupStatus>({
    phase: 'connecting',
    message: 'Waiting for services...',
  });
  const [isReady, setIsReady] = useState(false);

  const checkBackendReady = useCallback(async () => {
    setStartupStatus({
      phase: 'connecting',
      message: 'Waiting for services...',
      progress: 10,
    });

    let attempts = 0;
    
    while (attempts < MAX_STARTUP_RETRIES) {
      try {
        const response = await healthApi.checkReady();
        
        if (response.ready) {
          setStartupStatus({
            phase: 'ready',
            message: 'Ready!',
            progress: 100,
            componentStatuses: response.components?.map(c => ({
              name: c.name,
              status: c.status as 'pending' | 'healthy' | 'degraded' | 'unhealthy',
            })),
          });
          
          // Start health monitoring
          defaultHealthMonitor.start();
          
          // Small delay for smooth transition
          await new Promise(resolve => setTimeout(resolve, 300));
          setIsReady(true);
          return;
        }

        // Update status based on backend phase
        const progress = Math.min(20 + (attempts * 8), 90);
        setStartupStatus({
          phase: 'initializing',
          message: response.message || `Initializing: ${response.phase}`,
          progress,
          componentStatuses: response.components?.map(c => ({
            name: c.name,
            status: c.status as 'pending' | 'healthy' | 'degraded' | 'unhealthy',
          })),
        });

      } catch (error) {
        // Connection error - backend not yet available
        const progress = Math.min(10 + (attempts * 5), 50);
        setStartupStatus({
          phase: 'connecting',
          message: 'Waiting for services...',
          progress,
        });
      }

      attempts++;
      await new Promise(resolve => setTimeout(resolve, STARTUP_POLL_INTERVAL_MS));
    }

    // Max retries exceeded
    setStartupStatus({
      phase: 'timeout',
      message: 'Connection timed out',
      error: 'Could not connect to backend services. Please ensure the backend is running.',
    });
  }, []);

  const handleRetry = useCallback(() => {
    setIsReady(false);
    checkBackendReady();
  }, [checkBackendReady]);

  useEffect(() => {
    // Check if running in Electron with startup orchestration
    const electronStartup = (window as any).electronAPI?.getStartupStatus;
    
    if (electronStartup) {
      // Electron handles startup orchestration - listen for status updates
      const onStartupStatus = (window as any).electronAPI?.onStartupStatus;
      if (onStartupStatus) {
        let lastPhase = '';
        let lastProgress = -1;
        let messageCount = 0;
        let hasTransitionedToReady = false;  // Prevent duplicate ready transitions
        
        const cleanup = onStartupStatus((status: any) => {
          messageCount++;
          
          // Skip all messages after we've transitioned to ready
          if (hasTransitionedToReady) {
            return;
          }
          
          // Only log and update if there's a meaningful change
          const currentPhase = status?.phase || '';
          const currentProgress = Math.floor((status?.progress || 0) / 10) * 10;  // Round to 10%
          
          // Always process 'ready' and 'error' phases immediately
          const isImportantPhase = currentPhase === 'ready' || currentPhase === 'error';
          const hasChanged = currentPhase !== lastPhase || currentProgress !== lastProgress;
          
          if (isImportantPhase || hasChanged) {
            // Only log occasionally to avoid console spam
            if (messageCount <= 3 || messageCount % 10 === 0 || isImportantPhase) {
              console.log(`[App] Startup status #${messageCount}: phase=${currentPhase}, progress=${status?.progress}`);
            }
            
            lastPhase = currentPhase;
            lastProgress = currentProgress;
            
            if (currentPhase === 'ready') {
              hasTransitionedToReady = true;  // Mark as transitioned
              console.log('[App] Backend ready! Transitioning to main app...');
              setStartupStatus({ phase: 'ready', message: 'Ready!', progress: 100 });
              defaultHealthMonitor.start();
              // Only set ready once to prevent re-renders
              setIsReady((prev) => {
                if (!prev) {
                  console.log('[App] Setting isReady to true');
                  return true;
                }
                return prev;
              });
            } else if (currentPhase === 'error' || status?.error) {
              setStartupStatus({
                phase: 'error',
                message: status.message || 'Startup failed',
                error: status.error || status.message,
              });
            } else {
              // Update with current phase
              setStartupStatus({
                phase: currentPhase === 'waiting_for_backend' ? 'connecting' : 'initializing',
                message: status?.message || `Phase: ${currentPhase}`,
                progress: status?.progress || 50,
              });
            }
          }
        });
        
        // Store cleanup function
        return () => {
          console.log(`[App] Cleanup: received ${messageCount} status messages total`);
          if (cleanup) cleanup();
          defaultHealthMonitor.stop();
        };
      }
      
      // Get initial status
      electronStartup().then((status: any) => {
        console.log('[App] Initial startup status:', status);
        if (status?.phase === 'ready') {
          setStartupStatus({ phase: 'ready', message: 'Ready!' });
          defaultHealthMonitor.start();
          setIsReady(true);
        } else if (status?.phase === 'error') {
          setStartupStatus({
            phase: 'error',
            message: status.message || 'Startup failed',
            error: status.error || status.message,
          });
        }
        // Otherwise wait for status updates via IPC
      }).catch((err: any) => {
        console.error('[App] Failed to get startup status:', err);
        // Fall back to polling
        checkBackendReady();
      });
    } else {
      // Browser mode - poll for backend readiness
      checkBackendReady();
    }

    return () => {
      defaultHealthMonitor.stop();
    };
  }, [checkBackendReady]);

  return (
    <>
      <LoadingScreen 
        status={startupStatus} 
        onRetry={handleRetry}
      />
      {isReady && (
        <Router>
          {AUTH_ENABLED ? (
            <Routes>
              {/* Public auth routes */}
              <Route path="/login" element={<Login />} />
              <Route path="/mfa-verify" element={<MFAVerify />} />
              <Route path="/sso/callback" element={<SSOCallback />} />
              
              {/* Password change route (requires auth but allows password change) */}
              <Route
                path="/change-password"
                element={
                  <ProtectedRoute allowPasswordChange>
                    <ChangePassword forced />
                  </ProtectedRoute>
                }
              />
              
              {/* Protected main application */}
              <Route
                path="/*"
                element={
                  <ProtectedRoute>
                    <WizardProvider>
                      <WizardShell />
                    </WizardProvider>
                  </ProtectedRoute>
                }
              />
            </Routes>
          ) : (
            /* Auth disabled - direct access to wizard */
            <WizardProvider>
              <WizardShell />
            </WizardProvider>
          )}
        </Router>
      )}
    </>
  )
}

export default App
