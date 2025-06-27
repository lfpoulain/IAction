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
            // Utiliser l'API rapide par défaut
            const response = await fetch('/api/cameras/quick');
            const cameras = await response.json();
            
            select.innerHTML = '<option value="">Sélectionnez une source...</option>';
            
            cameras.forEach(camera => {
                const option = document.createElement('option');
                option.value = camera.id;
                option.textContent = camera.name;
                if (camera.type === 'rtsp_preset') {
                    option.setAttribute('data-template', camera.url_template || '');
                }
                select.appendChild(option);
            });
            
            this.addLog(`${cameras.filter(c => c.type === 'usb').length} caméra(s) USB détectée(s)`, 'info');
        } catch (error) {
            console.error('Erreur lors du chargement des caméras:', error);
            select.innerHTML = '<option value="">Erreur de détection</option>';
            this.addLog('Erreur lors du chargement des caméras', 'error');
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
        loadingOption.textContent = 'Détection des vraies caméras USB...';
        loadingOption.disabled = true;
        select.innerHTML = '';
        select.appendChild(loadingOption);
        
        this.addLog('Détection des caméras USB en cours...', 'info');
        
        try {
            // Utiliser l'API complète pour détecter les vraies caméras
            const response = await fetch('/api/cameras');
            const cameras = await response.json();
            
            select.innerHTML = '<option value="">Sélectionnez une source...</option>';
            
            cameras.forEach(camera => {
                const option = document.createElement('option');
                option.value = camera.id;
                option.textContent = camera.name;
                if (camera.type === 'rtsp_preset') {
                    option.setAttribute('data-template', camera.url_template || '');
                }
                select.appendChild(option);
            });
            
            const usbCount = cameras.filter(c => c.type === 'usb').length;
            this.addLog(`Détection terminée: ${usbCount} caméra(s) USB trouvée(s)`, 'success');
            
        } catch (error) {
            console.error('Erreur lors de la détection:', error);
            select.innerHTML = '<option value="">Erreur de détection</option>';
            this.addLog('Erreur lors de la détection des caméras', 'error');
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
        const type = selectedOption.dataset.type;
        
        if (type === 'rtsp' && source === 'rtsp_custom') {
            const rtspUrl = document.getElementById('rtsp-url').value.trim();
            if (!rtspUrl) {
                this.addLog('Veuillez saisir une URL RTSP', 'warning');
                return;
            }
            source = rtspUrl;
        }
        
        try {
            const response = await fetch('/api/start_capture', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    source: source,
                    type: type
                })
            });
            
            const result = await response.json();
            
            if (response.ok) {
                this.isCapturing = true;
                this.updateCaptureControls();
                this.startVideoStream();
                this.addLog(`Capture démarrée: ${selectedOption.textContent}`, 'success');
            } else {
                this.addLog(`Erreur: ${result.error}`, 'error');
            }
        } catch (error) {
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
        
        videoStream.src = '/video_feed?' + new Date().getTime();
        videoStream.style.display = 'block';
        noVideo.style.display = 'none';
        
        // Mettre à jour le flux périodiquement
        this.videoUpdateInterval = setInterval(() => {
            if (this.isCapturing) {
                videoStream.src = '/video_feed?' + new Date().getTime();
            }
        }, 5000);
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
        this.statusInterval = setInterval(() => {
            this.updateSensorValues();
        }, 2000);
    }
    
    async updateSensorValues() {
        // Cette fonction pourrait être étendue pour récupérer les valeurs des capteurs
        // depuis une API dédiée si nécessaire
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
    
    clearLogs() {
        const logContainer = document.getElementById('activity-log');
        logContainer.innerHTML = '<div class="text-muted">En attente d\'activité...</div>';
    }
}

// Initialiser l'application
const app = new IActionApp();
