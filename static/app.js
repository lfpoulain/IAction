// Application JavaScript pour IAction

class IActionApp {
    constructor() {
        this.isCapturing = false;
        this.detections = [];
        this.statusInterval = null;
        this.videoUpdateInterval = null;
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
        this.loadCameraSources();
        this.loadDetections();
        this.startStatusUpdates();
        this.addLog('Application initialisée', 'info');
    }
    
    setupEventListeners() {
        // Contrôles de capture
        document.getElementById('start-capture').addEventListener('click', () => this.startCapture());
        document.getElementById('stop-capture').addEventListener('click', () => this.stopCapture());
        document.getElementById('emergency-stop').addEventListener('click', () => this.emergencyStop());
        
        // Sélection de caméra
        document.getElementById('camera-select').addEventListener('change', (e) => {
            const rtspConfig = document.getElementById('rtsp-config');
            if (e.target.value === 'rtsp_custom') {
                rtspConfig.style.display = 'block';
            } else {
                rtspConfig.style.display = 'none';
            }
        });
        
        // Détection des caméras
        document.getElementById('detect-cameras').addEventListener('click', () => this.detectRealCameras());
        
        // Détections
        document.getElementById('add-detection').addEventListener('click', () => this.showAddDetectionModal());
        document.getElementById('save-detection').addEventListener('click', () => this.saveDetection());
        
        // Logs
        document.getElementById('clear-logs').addEventListener('click', () => this.clearLogs());
        
        // Modal
        const modal = new bootstrap.Modal(document.getElementById('addDetectionModal'));
        this.addDetectionModal = modal;
    }
    
    async loadCameraSources() {
        const select = document.getElementById('camera-select');
        const loadingOption = document.createElement('option');
        loadingOption.value = '';
        loadingOption.textContent = 'Détection des caméras en cours...';
        loadingOption.disabled = true;
        select.innerHTML = '';
        select.appendChild(loadingOption);
        
        try {
            const response = await fetch('/api/cameras');
            const data = await response.json();
            
            if (data.success) {
                const cameras = data.cameras;
                select.innerHTML = '<option value="">Sélectionnez une source...</option>';
                
                cameras.forEach(camera => {
                    const option = document.createElement('option');
                    option.value = camera.id;
                    option.textContent = camera.name;
                    option.setAttribute('data-type', camera.type);
                    
                    // Ajouter des attributs pour les caméras RTSP
                    if (camera.type === 'rtsp' && camera.url) {
                        option.setAttribute('data-url', camera.url);
                    }
                    
                    // Ajouter le statut de connexion pour les caméras RTSP
                    if (camera.test_status) {
                        const statusEmoji = {
                            'online': '🟢',
                            'offline': '🔴',
                            'error': '⚠️',
                            'not_configured': '⚪'
                        };
                        option.textContent += ` ${statusEmoji[camera.test_status] || ''}`;
                    }
                    
                    select.appendChild(option);
                });
                
                const usbCount = data.usb_count || 0;
                const rtspCount = data.rtsp_count || 0;
                
                this.addLog(`Caméras détectées: ${usbCount} USB, ${rtspCount} RTSP`, 'info');
                
                // Mise à jour du bouton de détection
                this.updateDetectionButton(data.count);
            } else {
                throw new Error(data.error || 'Erreur inconnue');
            }
        } catch (error) {
            console.error('Erreur lors du chargement des caméras:', error);
            select.innerHTML = '<option value="">Erreur de détection</option>';
            this.addLog(`Erreur lors du chargement des caméras: ${error.message}`, 'error');
        }
    }
    
    async detectRealCameras() {
        const select = document.getElementById('camera-select');
        const detectBtn = document.getElementById('detect-cameras');
        
        // Désactiver le bouton et afficher le chargement
        detectBtn.disabled = true;
        detectBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
        
        const loadingOption = document.createElement('option');
        loadingOption.value = '';
        loadingOption.textContent = 'Rafraîchissement des caméras...';
        loadingOption.disabled = true;
        select.innerHTML = '';
        select.appendChild(loadingOption);
        
        this.addLog('Rafraîchissement de la liste des caméras...', 'info');
        
        try {
            // Utiliser l'API de rafraîchissement pour forcer la mise à jour
            const response = await fetch('/api/cameras/refresh', {
                method: 'POST'
            });
            const data = await response.json();
            
            if (data.success) {
                const cameras = data.cameras;
                select.innerHTML = '<option value="">Sélectionnez une source...</option>';
                
                cameras.forEach(camera => {
                    const option = document.createElement('option');
                    option.value = camera.id;
                    option.textContent = camera.name;
                    option.setAttribute('data-type', camera.type);
                    
                    // Ajouter des attributs pour les caméras RTSP
                    if (camera.type === 'rtsp' && camera.url) {
                        option.setAttribute('data-url', camera.url);
                    }
                    
                    // Ajouter le statut de connexion pour les caméras RTSP
                    if (camera.test_status) {
                        const statusEmoji = {
                            'online': '🟢',
                            'offline': '🔴',
                            'error': '⚠️',
                            'not_configured': '⚪'
                        };
                        option.textContent += ` ${statusEmoji[camera.test_status] || ''}`;
                    }
                    
                    select.appendChild(option);
                });
                
                const usbCount = data.usb_count || 0;
                const rtspCount = data.rtsp_count || 0;
                
                this.addLog(`Mise à jour terminée: ${usbCount} USB, ${rtspCount} RTSP trouvée(s)`, 'success');
                this.updateDetectionButton(data.count);
            } else {
                throw new Error(data.error || 'Erreur lors du rafraîchissement');
            }
        } catch (error) {
            console.error('Erreur lors de la détection:', error);
            select.innerHTML = '<option value="">Erreur de détection</option>';
            this.addLog(`Erreur lors du rafraîchissement: ${error.message}`, 'error');
        } finally {
            // Réactiver le bouton
            detectBtn.disabled = false;
            detectBtn.innerHTML = '<i class="bi bi-search"></i>';
        }
    }
    
    async loadDetections() {
        try {
            const response = await fetch('/api/detections');
            const detections = await response.json();
            
            this.detections = detections;
            this.updateDetectionsList();
            
            this.addLog(`${detections.length} détections chargées`, 'info');
        } catch (error) {
            this.addLog(`Erreur lors du chargement des détections: ${error.message}`, 'error');
        }
    }
    
    updateDetectionsList() {
        const container = document.getElementById('detections-list');
        
        if (this.detections.length === 0) {
            container.innerHTML = '<p class="text-muted">Aucune détection configurée</p>';
            return;
        }
        
        container.innerHTML = '';
        
        this.detections.forEach(detection => {
            const item = document.createElement('div');
            item.className = 'detection-item';
            item.innerHTML = `
                <div class="detection-name">${detection.name}</div>
                <div class="detection-phrase">${detection.phrase}</div>
                <div class="detection-controls">
                    <span class="badge status-badge bg-secondary">Inactif</span>
                    <button class="btn btn-danger btn-sm" onclick="app.removeDetection('${detection.id}')">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            `;
            item.id = `detection-${detection.id}`;
            container.appendChild(item);
        });
    }
    
    async startCapture() {
        const select = document.getElementById('camera-select');
        const selectedOption = select.options[select.selectedIndex];
        
        if (!selectedOption || !selectedOption.value) {
            this.addLog('Veuillez sélectionner une source vidéo', 'warning');
            return;
        }
        
        let source = selectedOption.value;
        let type = selectedOption.getAttribute('data-type') || 'usb';
        let rtspUrl = null;
        
        // Gestion spéciale pour RTSP personnalisé
        if (source === 'rtsp_custom') {
            type = 'rtsp';
            rtspUrl = document.getElementById('rtsp-url').value.trim();
            if (!rtspUrl) {
                this.addLog('Veuillez saisir une URL RTSP', 'warning');
                return;
            }
            source = rtspUrl;
        } else if (type === 'rtsp') {
            // Pour les caméras RTSP préconfigurées
            rtspUrl = selectedOption.getAttribute('data-url') || null;
        }
        
        console.log(`Démarrage capture - Source: ${source}, Type: ${type}, RTSP URL: ${rtspUrl}`);
        
        try {
            const requestBody = {
                source: source,
                type: type
            };
            
            if (rtspUrl) {
                requestBody.rtsp_url = rtspUrl;
            }
            
            const response = await fetch('/api/start_capture', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(requestBody)
            });
            
            const result = await response.json();
            
            if (result.success || response.ok) {
                this.isCapturing = true;
                this.updateCaptureControls();
                this.startVideoStream();
                
                const message = result.message || `Capture démarrée: ${selectedOption.textContent}`;
                this.addLog(message, 'success');
                
                // Afficher les infos de la caméra si disponibles
                if (result.camera) {
                    this.displayCameraInfo(result.camera);
                }
            } else {
                const errorMsg = result.error || 'Erreur lors du démarrage';
                this.addLog(`Erreur: ${errorMsg}`, 'error');
            }
        } catch (error) {
            console.error('Erreur lors du démarrage:', error);
            this.addLog(`Erreur lors du démarrage: ${error.message}`, 'error');
        }
    }
    
    async stopCapture() {
        try {
            const response = await fetch('/api/stop_capture', {
                method: 'POST'
            });
            
            const result = await response.json();
            
            if (response.ok) {
                this.isCapturing = false;
                this.updateCaptureControls();
                this.stopVideoStream();
                this.addLog('Capture arrêtée', 'info');
            } else {
                this.addLog(`Erreur: ${result.error}`, 'error');
            }
        } catch (error) {
            this.addLog(`Erreur lors de l'arrêt: ${error.message}`, 'error');
        }
    }
    
    emergencyStop() {
        this.stopCapture();
        this.addLog('ARRÊT D\'URGENCE ACTIVÉ', 'error');
    }
    
    updateCaptureControls() {
        const startBtn = document.getElementById('start-capture');
        const stopBtn = document.getElementById('stop-capture');
        const statusIndicator = document.getElementById('status-indicator');
        
        if (this.isCapturing) {
            startBtn.disabled = true;
            stopBtn.disabled = false;
            statusIndicator.textContent = 'En cours';
            statusIndicator.className = 'badge bg-success status-running';
        } else {
            startBtn.disabled = false;
            stopBtn.disabled = true;
            statusIndicator.textContent = 'Arrêté';
            statusIndicator.className = 'badge bg-secondary status-stopped';
        }
    }
    
    startVideoStream() {
        const videoStream = document.getElementById('video-stream');
        const noVideo = document.getElementById('no-video');
        
        // Ajouter un paramètre unique pour éviter la mise en cache
        videoStream.src = '/video_feed?' + new Date().getTime();
        videoStream.style.display = 'block';
        noVideo.style.display = 'none';
        
        // Supprimer la mise à jour périodique du flux vidéo qui cause des reconnexions
        // Le flux MJPEG est déjà en streaming continu et n'a pas besoin d'être rechargé
        if (this.videoUpdateInterval) {
            clearInterval(this.videoUpdateInterval);
        }
        
        // Ajouter un gestionnaire d'erreur pour le flux vidéo
        videoStream.onerror = () => {
            console.log("Erreur de chargement du flux vidéo, tentative de reconnexion...");
            setTimeout(() => {
                if (this.isCapturing) {
                    videoStream.src = '/video_feed?' + new Date().getTime();
                }
            }, 2000);
        };
    }
    
    stopVideoStream() {
        const videoStream = document.getElementById('video-stream');
        const noVideo = document.getElementById('no-video');
        
        if (this.videoUpdateInterval) {
            clearInterval(this.videoUpdateInterval);
            this.videoUpdateInterval = null;
        }
        
        videoStream.style.display = 'none';
        videoStream.src = '';
        noVideo.style.display = 'block';
    }
    
    showAddDetectionModal() {
        document.getElementById('detection-name').value = '';
        document.getElementById('detection-phrase').value = '';
        this.addDetectionModal.show();
    }
    
    async saveDetection() {
        const name = document.getElementById('detection-name').value.trim();
        const phrase = document.getElementById('detection-phrase').value.trim();
        
        if (!name || !phrase) {
            this.addLog('Nom et phrase requis pour la détection', 'warning');
            return;
        }
        
        try {
            const response = await fetch('/api/detections', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    name: name,
                    phrase: phrase
                })
            });
            
            const result = await response.json();
            
            if (response.ok) {
                this.addDetectionModal.hide();
                this.loadDetections();
                this.addLog(`Détection ajoutée: ${name}`, 'success');
            } else {
                this.addLog(`Erreur: ${result.error}`, 'error');
            }
        } catch (error) {
            this.addLog(`Erreur lors de l'ajout: ${error.message}`, 'error');
        }
    }
    
    async removeDetection(detectionId) {
        if (!confirm('Êtes-vous sûr de vouloir supprimer cette détection ?')) {
            return;
        }
        
        try {
            const response = await fetch(`/api/detections/${detectionId}`, {
                method: 'DELETE'
            });
            
            const result = await response.json();
            
            if (response.ok) {
                this.loadDetections();
                this.addLog('Détection supprimée', 'info');
            } else {
                this.addLog(`Erreur: ${result.error}`, 'error');
            }
        } catch (error) {
            this.addLog(`Erreur lors de la suppression: ${error.message}`, 'error');
        }
    }
    
    startStatusUpdates() {
        // Augmenter l'intervalle de mise à jour pour réduire le nombre de requêtes
        // Passer de 2 secondes à 5 secondes
        this.statusInterval = setInterval(() => {
            this.updateSensorValues();
        }, 5000);
    }
    
    async updateSensorValues() {
        try {
            // Récupérer les informations de statut depuis l'API
            const response = await fetch('/api/status');
            if (response.ok) {
                const data = await response.json();
                
                // Mettre à jour les indicateurs de temps d'analyse
                this.updateAnalysisTimeIndicators(data);
            }
        } catch (error) {
            console.error('Erreur lors de la récupération des valeurs des capteurs:', error);
        }
    }
    
    updateAnalysisTimeIndicators(statusData) {
        const lastAnalysisTimeElement = document.getElementById('last-analysis-time');
        const analysisDurationElement = document.getElementById('analysis-duration');
        
        if (statusData.last_analysis_time) {
            // Calculer le temps écoulé depuis la dernière analyse
            const now = Date.now() / 1000; // Timestamp actuel en secondes
            const elapsed = now - statusData.last_analysis_time;
            
            if (elapsed < 60) {
                lastAnalysisTimeElement.textContent = `${Math.round(elapsed)}s`;
            } else if (elapsed < 3600) {
                lastAnalysisTimeElement.textContent = `${Math.floor(elapsed / 60)}m ${Math.round(elapsed % 60)}s`;
            } else {
                lastAnalysisTimeElement.textContent = `${Math.floor(elapsed / 3600)}h ${Math.floor((elapsed % 3600) / 60)}m`;
            }
        } else {
            lastAnalysisTimeElement.textContent = '-';
        }
        
        if (statusData.last_analysis_duration) {
            analysisDurationElement.textContent = `${statusData.last_analysis_duration}s`;
        } else {
            analysisDurationElement.textContent = '-';
        }
    }
    
    addLog(message, type = 'info') {
        const logContainer = document.getElementById('activity-log');
        const timestamp = new Date().toLocaleTimeString();
        
        const logEntry = document.createElement('div');
        logEntry.className = 'log-entry';
        logEntry.innerHTML = `
            <span class="log-timestamp">[${timestamp}]</span>
            <span class="log-message log-${type}">${message}</span>
        `;
        
        // Supprimer le message "En attente d'activité" s'il existe
        const waitingMessage = logContainer.querySelector('.text-muted');
        if (waitingMessage) {
            waitingMessage.remove();
        }
        
        logContainer.appendChild(logEntry);
        
        // Limiter le nombre d'entrées de log
        const entries = logContainer.querySelectorAll('.log-entry');
        if (entries.length > 100) {
            entries[0].remove();
        }
        
        // Faire défiler vers le bas
        logContainer.scrollTop = logContainer.scrollHeight;
    }
    
    updateDetectionButton(cameraCount) {
        const detectBtn = document.getElementById('detect-cameras');
        if (detectBtn) {
            const originalTitle = 'Détecter les vraies caméras USB';
            if (cameraCount > 0) {
                detectBtn.title = `${originalTitle} (${cameraCount} détectées)`;
                detectBtn.classList.add('btn-outline-success');
                detectBtn.classList.remove('btn-outline-secondary');
            } else {
                detectBtn.title = originalTitle;
                detectBtn.classList.add('btn-outline-secondary');
                detectBtn.classList.remove('btn-outline-success');
            }
        }
    }
    
    displayCameraInfo(camera) {
        if (!camera) return;
        
        const infoMessage = [];
        if (camera.type === 'usb') {
            infoMessage.push(`Type: Caméra USB`);
            if (camera.resolution) {
                infoMessage.push(`Résolution: ${camera.resolution}`);
            }
            if (camera.path) {
                infoMessage.push(`Périphérique: ${camera.path}`);
            }
        } else if (camera.type === 'rtsp') {
            infoMessage.push(`Type: Caméra IP (RTSP)`);
            if (camera.test_status) {
                const statusText = {
                    'online': 'En ligne',
                    'offline': 'Hors ligne',
                    'error': 'Erreur de connexion',
                    'not_configured': 'Non configurée'
                };
                infoMessage.push(`Statut: ${statusText[camera.test_status] || 'Inconnu'}`);
            }
        }
        
        if (infoMessage.length > 0) {
            this.addLog(`Infos caméra - ${infoMessage.join(', ')}`, 'info');
        }
    }
    
    clearLogs() {
        const logContainer = document.getElementById('activity-log');
        if (logContainer) {
            logContainer.innerHTML = '<div class="text-muted">En attente d\'activité...</div>';
        }
    }
}

// Initialiser l'application
const app = new IActionApp();
