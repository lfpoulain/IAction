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
        this.loadConfig();
        this.loadDetections();
        this.startStatusUpdates();
        this.addLog('Application initialisée', 'info');
    }
    
    async loadConfig() {
        try {
            const response = await fetch('/api/config');
            const config = await response.json();
            
            if (config.rtsp_url) {
                document.getElementById('rtsp-url').value = config.rtsp_url;
                this.addLog('Configuration RTSP chargée depuis le serveur.', 'info');
            }
        } catch (error) {
            this.addLog('Erreur lors du chargement de la configuration: ' + error.message, 'error');
        }
    }

    setupEventListeners() {
        // Contrôles de capture
        document.getElementById('start-capture').addEventListener('click', () => this.startCapture());
        document.getElementById('stop-capture').addEventListener('click', () => this.stopCapture());
        document.getElementById('emergency-stop').addEventListener('click', () => this.emergencyStop());
        
        // Détections
        document.getElementById('add-detection').addEventListener('click', () => this.showAddDetectionModal());
        document.getElementById('save-detection').addEventListener('click', () => this.saveDetection());
        
        // Logs
        document.getElementById('clear-logs').addEventListener('click', () => this.clearLogs());
        
        // Flux vidéo
        document.getElementById('toggle-video-stream').addEventListener('click', () => this.toggleVideoStream());
        
        // Modal
        this.addDetectionModal = new bootstrap.Modal(document.getElementById('addDetectionModal'));
        
        // Suivi des analyses
        this.lastAnalysisTime = 0;
        
        // Suivi du flux vidéo
        this.isVideoStreamVisible = false;
        this.captureInProgress = false;
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
        const rtspUrl = document.getElementById('rtsp-url').value.trim();
        if (!rtspUrl) {
            this.addLog('Veuillez saisir une URL RTSP valide.', 'warning');
            return;
        }

        this.addLog(`Démarrage de la capture RTSP : ${rtspUrl}`, 'info');

        try {
            const response = await fetch('/api/start_capture', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    source: rtspUrl,
                    type: 'rtsp',
                    rtsp_url: rtspUrl
                })
            });

            const result = await response.json();

            if (result.success || response.ok) {
                this.isCapturing = true;
                this.captureInProgress = true;
                this.updateCaptureControls();
                this.showToggleButton();
                // Ne pas démarrer automatiquement le flux vidéo

                const message = result.message || `Capture démarrée avec succès.`;
                this.addLog(message, 'success');

                if (result.camera) {
                    this.displayCameraInfo(result.camera);
                }
            } else {
                const errorMsg = result.error || 'Erreur inconnue lors du démarrage de la capture.';
                this.addLog(`Erreur: ${errorMsg}`, 'error');
            }
        } catch (error) {
            console.error('Erreur de démarrage de la capture:', error);
            this.addLog(`Erreur critique lors du démarrage: ${error.message}`, 'error');
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
                this.captureInProgress = false;
                this.updateCaptureControls();
                this.hideToggleButton();
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
        // Mise à jour rapide pour réactivité en temps réel
        this.statusInterval = setInterval(() => {
            this.updateSensorValues();
        }, 1000); // 1 seconde pour meilleure réactivité
    }
    
    async updateSensorValues() {
        try {
            // Utiliser l'endpoint léger pour les métriques
            const response = await fetch('/api/metrics');
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
        const duration = statusData.last_analysis_duration;
        const analysisTime = statusData.last_analysis_time;
        const isValidDuration = duration && duration > 0;
        
        // Détecter une nouvelle analyse
        if (analysisTime && analysisTime !== this.lastAnalysisTime) {
            this.lastAnalysisTime = analysisTime;
            // Ajouter un effet visuel pour indiquer une nouvelle analyse
            const fpsElement = document.getElementById('analysis-fps');
            fpsElement.style.color = '#28a745'; // Vert pour nouvelle donnée
            setTimeout(() => fpsElement.style.color = '', 1000); // Retour normal après 1s
        }
        
        // Mise à jour optimisée en une seule fois
        document.getElementById('analysis-fps').textContent = 
            isValidDuration ? (1 / duration).toFixed(2) : '0.00';
        document.getElementById('analysis-duration').textContent = 
            isValidDuration ? duration.toFixed(2) : '0.00';
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
        
        // Limiter le nombre d'entrées de log pour les performances
        const entries = logContainer.querySelectorAll('.log-entry');
        if (entries.length > 50) {
            // Supprimer les 10 plus anciens d'un coup
            for (let i = 0; i < 10 && i < entries.length; i++) {
                entries[i].remove();
            }
        }
        
        // Faire défiler vers le bas
        logContainer.scrollTop = logContainer.scrollHeight;
    }
    
    // Fonction supprimée - plus de détection USB nécessaire
    
    displayCameraInfo(camera) {
        if (!camera || camera.type !== 'rtsp') return;
        
        const infoMessage = ['Type: Caméra RTSP'];
        
        if (camera.test_status) {
            const statusText = {
                'online': 'En ligne',
                'offline': 'Hors ligne', 
                'error': 'Erreur de connexion',
                'not_configured': 'Non configurée'
            };
            infoMessage.push(`Statut: ${statusText[camera.test_status] || 'Inconnu'}`);
        }
        
        this.addLog(`Infos caméra - ${infoMessage.join(', ')}`, 'info');
    }
    
    showToggleButton() {
        const toggleButton = document.getElementById('toggle-video-stream');
        toggleButton.style.display = 'block';
        this.addLog('Bouton "Voir le flux live" disponible', 'info');
    }
    
    hideToggleButton() {
        const toggleButton = document.getElementById('toggle-video-stream');
        toggleButton.style.display = 'none';
        // Réinitialiser l'état du flux vidéo
        this.isVideoStreamVisible = false;
    }
    
    toggleVideoStream() {
        const videoStream = document.getElementById('video-stream');
        const noVideo = document.getElementById('no-video');
        const toggleButton = document.getElementById('toggle-video-stream');
        const toggleText = document.getElementById('toggle-video-text');
        const toggleIcon = toggleButton.querySelector('i');
        
        if (this.isVideoStreamVisible) {
            // Masquer le flux
            videoStream.style.display = 'none';
            noVideo.style.display = 'block';
            toggleText.textContent = 'Voir le flux live';
            toggleIcon.className = 'bi bi-eye';
            this.isVideoStreamVisible = false;
            this.addLog('Flux vidéo masqué', 'info');
        } else {
            // Afficher le flux (seulement si capture en cours)
            if (this.captureInProgress) {
                videoStream.src = `/video_feed?t=${Date.now()}`;
                videoStream.style.display = 'block';
                noVideo.style.display = 'none';
                toggleText.textContent = 'Masquer le flux';
                toggleIcon.className = 'bi bi-eye-slash';
                this.isVideoStreamVisible = true;
                this.addLog('Flux vidéo affiché', 'info');
            } else {
                this.addLog('Aucune capture en cours - Démarrez d\'abord la capture', 'warning');
            }
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
