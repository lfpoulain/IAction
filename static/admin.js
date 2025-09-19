class AdminApp {
    constructor() {
        // Gestion des niveaux de logs (UI + console Chrome)
        this.logLevels = { 'error': 0, 'warning': 1, 'info': 2, 'success': 2, 'debug': 3 };
        this.logLevel = 'info';
        this.lastUiLog = { key: null, count: 0, el: null, ts: 0 };

        this.initializeEventListeners();
        this.initLogLevelFromUrl();
        this.applyLogLevelToUi();
        this.loadConfiguration();
        this.setupFormValidation();
    }

    // Utilitaire: fetch avec timeout pour éviter les longues attentes
    async fetchWithTimeout(resource, options = {}) {
        const { timeout = 3000 } = options;
        const controller = new AbortController();
        const id = setTimeout(() => controller.abort(), timeout);
        try {
            const response = await fetch(resource, { ...options, signal: controller.signal, cache: 'no-store' });
            return response;
        } finally {
            clearTimeout(id);
        }
    }

    async hotReload() {
        try {
            this.addLog('🔄 Rechargement à chaud de la configuration...', 'info');
            const res = await this.fetchWithTimeout('/api/admin/reload', { method: 'POST', timeout: 5000 });
            if (!res.ok) throw new Error(`Erreur HTTP: ${res.status}`);
            const data = await res.json();
            if (data.success) {
                this.addLog('✅ Configuration rechargée sans redémarrage', 'success');
                if (data.status) this.consoleLog('debug', data.status);
                // Recharger les valeurs dans le formulaire depuis le backend
                await this.loadConfiguration();
                return true;
            } else {
                this.addLog(`❌ Échec du rechargement: ${data.error || 'inconnu'}`, 'error');
                return false;
            }
        } catch (e) {
            this.addLog(`❌ Erreur rechargement: ${e.message}`, 'error');
            return false;
        }
    }

    // Helpers d'affichage pour les badges de statut
    setBadge(badgeId, state, text, title = '') {
        const el = document.getElementById(badgeId);
        if (!el) return;
        el.classList.remove('bg-secondary', 'bg-success', 'bg-danger', 'bg-warning', 'bg-info');
        const map = { loading: 'bg-warning', ok: 'bg-success', error: 'bg-danger', info: 'bg-info', idle: 'bg-secondary' };
        el.classList.add(map[state] || 'bg-secondary');
        el.textContent = text;
        if (title) el.setAttribute('title', title);
    }

    // Attendre que le serveur redevienne disponible après redémarrage
    async waitForServerBack(maxSeconds = 60) {
        const start = Date.now();
        while ((Date.now() - start) / 1000 < maxSeconds) {
            try {
                const res = await this.fetchWithTimeout('/api/metrics', { timeout: 2000 });
                if (res && res.ok) {
                    return true;
                }
            } catch (_) {
                // serveur pas encore dispo
            }
            await new Promise(r => setTimeout(r, 1000));
        }
        return false;
    }

    initializeEventListeners() {
        // Soumission du formulaire
        document.getElementById('config-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveConfiguration();
        });

        // Bouton recharger
        document.getElementById('reload-config').addEventListener('click', () => {
            this.hotReload();
        });

        // Bouton redémarrer
        document.getElementById('restart-app').addEventListener('click', () => {
            this.restartApplication();
        });

        // Bouton tester IA
        const testAiBtn = document.getElementById('test-ai');
        if (testAiBtn) {
            testAiBtn.addEventListener('click', () => this.testAI());
        }

        // Bouton tester MQTT
        const testMqttBtn = document.getElementById('test-mqtt');
        if (testMqttBtn) {
            testMqttBtn.addEventListener('click', () => this.testMQTT());
        }

        // Bouton tester RTSP
        const testRtspBtn = document.getElementById('test-rtsp');
        if (testRtspBtn) {
            testRtspBtn.addEventListener('click', () => this.testRTSP());
        }

        // Changement du mode API pour afficher/masquer les sections
        document.getElementById('ai_api_mode').addEventListener('change', (e) => {
            this.toggleApiSections(e.target.value);
        });

        // Changement du mode de capture (RTSP vs HA Polling)
        const captureModeEl = document.getElementById('capture_mode');
        if (captureModeEl) {
            captureModeEl.addEventListener('change', (e) => {
                this.toggleCaptureSections(e.target.value);
            });
        }

        // Sélecteur de niveau de logs
        const logSelect = document.getElementById('log-level-select');
        if (logSelect) {
            logSelect.addEventListener('change', (e) => {
                const lvl = (e.target.value || 'info').toLowerCase();
                if (lvl in this.logLevels) {
                    this.logLevel = lvl;
                    localStorage.setItem('ADMIN_LOG_LEVEL', lvl);
                    this.addLog(`Niveau de logs UI réglé sur: ${lvl.toUpperCase()}`, 'info');
                }
            });
        }
    }

    setupFormValidation() {
        // Validation en temps réel des champs
        const form = document.getElementById('config-form');
        const inputs = form.querySelectorAll('input, select');
        
        inputs.forEach(input => {
            input.addEventListener('input', () => {
                this.validateField(input);
            });
        });
    }

    validateField(field) {
        // Validation basique des champs
        field.classList.remove('is-invalid', 'is-valid');
        // Ne pas valider les champs masqués
        if (!field || field.offsetParent === null) {
            return true;
        }
        
        if (field.type === 'url' && field.value && !this.isValidUrl(field.value)) {
            field.classList.add('is-invalid');
            return false;
        }
        
        if (field.type === 'number' && field.value !== '') {
            // Accepter la virgule comme séparateur décimal (ex: 1,5)
            const raw = field.value.trim().replace(',', '.');
            if (raw !== field.value) {
                field.value = raw; // normaliser visuellement aussi
            }
            const val = Number(raw);
            if (Number.isNaN(val)) {
                field.classList.add('is-invalid');
                return false;
            }
            const hasMin = field.min !== undefined && field.min !== '';
            const hasMax = field.max !== undefined && field.max !== '';
            if ((hasMin && val < Number(field.min)) || (hasMax && val > Number(field.max))) {
                field.classList.add('is-invalid');
                return false;
            }
        }
        
        if (field.value) {
            field.classList.add('is-valid');
        }
        
        return true;
    }

    isValidUrl(string) {
        try {
            new URL(string);
            return true;
        } catch (_) {
            return false;
        }
    }

    toggleApiSections(mode) {
        const openaiSection = document.getElementById('openai-config');
        const lmstudioSection = document.getElementById('lmstudio-config');
        const ollamaSection = document.getElementById('ollama-config');

        // Masquer tout par défaut
        if (openaiSection) openaiSection.style.display = 'none';
        if (lmstudioSection) lmstudioSection.style.display = 'none';
        if (ollamaSection) ollamaSection.style.display = 'none';

        // Afficher la section selon le mode
        if (mode === 'openai' && openaiSection) {
            openaiSection.style.display = 'block';
        } else if (mode === 'lmstudio' && lmstudioSection) {
            lmstudioSection.style.display = 'block';
        } else if (mode === 'ollama' && ollamaSection) {
            ollamaSection.style.display = 'block';
        }
    }

    toggleCaptureSections(mode) {
        const haSection = document.getElementById('ha-polling-config');
        const rtspUrl = document.getElementById('default_rtsp_url');
        const rtspUser = document.getElementById('rtsp_username');
        const rtspPass = document.getElementById('rtsp_password');

        if (mode === 'ha_polling') {
            if (haSection) haSection.style.display = 'flex';
            if (rtspUrl) rtspUrl.closest('.col-md-4').style.display = 'none';
            if (rtspUser) rtspUser.closest('.col-md-4').style.display = 'none';
            if (rtspPass) rtspPass.closest('.col-md-4').style.display = 'none';
        } else {
            if (haSection) haSection.style.display = 'none';
            if (rtspUrl) rtspUrl.closest('.col-md-4').style.display = '';
            if (rtspUser) rtspUser.closest('.col-md-4').style.display = '';
            if (rtspPass) rtspPass.closest('.col-md-4').style.display = '';
        }
    }

    async loadConfiguration() {
        try {
            this.addLog('🔄 Chargement de la configuration...', 'info');
            
            const response = await fetch('/api/admin/config');
            if (!response.ok) {
                throw new Error(`Erreur HTTP: ${response.status}`);
            }
            
            const config = await response.json();
            // D'abord appliquer les sections conditionnelles pour éviter de valider des champs masqués
            this.toggleApiSections(config.AI_API_MODE || 'lmstudio');
            this.toggleCaptureSections(config.CAPTURE_MODE || 'rtsp');
            // Puis remplir le formulaire (validation respectera la visibilité)
            this.populateForm(config);
            
            this.addLog('✅ Configuration chargée avec succès', 'success');
        } catch (error) {
            this.addLog(`❌ Erreur lors du chargement: ${error.message}`, 'error');
            console.error('Erreur lors du chargement de la configuration:', error);
        }
    }

    populateForm(config) {
        // Remplir tous les champs du formulaire
        Object.keys(config).forEach(key => {
            const field = document.querySelector(`[name="${key}"]`);
            if (field) {
                field.value = config[key] || '';
                this.validateField(field);
            }
        });
    }

    async saveConfiguration() {
        try {
            this.addLog('💾 Sauvegarde de la configuration...', 'info');
            
            // Collecter toutes les données du formulaire
            const formData = new FormData(document.getElementById('config-form'));
            const config = {};
            
            for (let [key, value] of formData.entries()) {
                config[key] = value;
            }
            
            // Validation côté client
            if (!this.validateConfiguration(config)) {
                this.addLog('❌ Configuration invalide, vérifiez les champs en rouge', 'error');
                return;
            }
            
            const response = await fetch('/api/admin/config', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(config)
            });
            
            if (!response.ok) {
                throw new Error(`Erreur HTTP: ${response.status}`);
            }
            
            const result = await response.json();
            
            if (result.success) {
                this.addLog('✅ Configuration sauvegardée avec succès', 'success');
                // Appliquer à chaud sans redémarrage
                const ok = await this.hotReload();
                if (!ok) {
                    this.addLog('⚠️ Application partielle des changements. Vous pouvez redémarrer pour forcer l\'application complète.', 'warning');
                }
            } else {
                this.addLog(`❌ Erreur: ${result.error}`, 'error');
            }
            
        } catch (error) {
            this.addLog(`❌ Erreur lors de la sauvegarde: ${error.message}`, 'error');
            console.error('Erreur lors de la sauvegarde:', error);
        }
    }

    validateConfiguration(config) {
        let isValid = true;
        const form = document.getElementById('config-form');
        const inputs = form.querySelectorAll('input, select');
        
        inputs.forEach(input => {
            if (!this.validateField(input)) {
                isValid = false;
            }
        });
        
        // Validations spécifiques
        if (config.AI_API_MODE === 'openai' && !config.OPENAI_API_KEY) {
            this.addLog('⚠️ Clé API OpenAI requise en mode OpenAI', 'warning');
        }
        if (config.AI_API_MODE === 'ollama') {
            if (!config.OLLAMA_MODEL) {
                this.addLog('⚠️ Modèle Ollama requis (ex: llava:latest)', 'warning');
            }
            if (config.OLLAMA_URL && !this.isValidUrl(config.OLLAMA_URL)) {
                this.addLog('⚠️ URL Ollama invalide', 'warning');
                isValid = false;
            }
        }
        
        if (!config.MQTT_BROKER) {
            this.addLog('⚠️ Adresse du broker MQTT requise', 'warning');
        }
        
        return isValid;
    }

    async restartApplication() {
        if (!confirm('Êtes-vous sûr de vouloir redémarrer l\'application ?')) {
            return;
        }
        
        try {
            this.addLog('🔄 Redémarrage de l\'application...', 'info');
            const restartBtn = document.getElementById('restart-app');
            if (restartBtn) restartBtn.disabled = true;
            
            const response = await fetch('/api/admin/restart', {
                method: 'POST'
            });
            
            if (response.ok) {
                this.addLog('✅ Redémarrage initié', 'success');
                this.addLog('⏳ Attente du retour du serveur...', 'info');

                // Polling pour attendre le retour du serveur
                const back = await this.waitForServerBack(60);
                if (back) {
                    this.addLog('✅ Serveur redémarré - rechargement...', 'success');
                    window.location.reload();
                } else {
                    this.addLog('⚠️ Impossible de confirmer le redémarrage. Rechargez la page manuellement.', 'warning');
                }
            } else {
                throw new Error(`Erreur HTTP: ${response.status}`);
            }
            
        } catch (error) {
            this.addLog(`❌ Erreur lors du redémarrage: ${error.message}`, 'error');
            console.error('Erreur lors du redémarrage:', error);
        } finally {
            const restartBtn = document.getElementById('restart-app');
            if (restartBtn) restartBtn.disabled = false;
        }
    }

    async testAI() {
        const btn = document.getElementById('test-ai');
        this.setBadge('test-ai-status', 'loading', '...');
        if (btn) btn.disabled = true;
        try {
            this.addLog('🧠 Test IA: démarrage...', 'info');
            const res = await this.fetchWithTimeout('/api/admin/ai_test', { timeout: 5000 });
            const data = await res.json();
            if (data.success) {
                this.setBadge('test-ai-status', 'ok', 'OK', `${data.api_mode} • ${data.current_model}`);
                this.addLog(`✅ IA OK (${data.api_mode}) - modèle: ${data.current_model}`, 'success');
            } else {
                this.setBadge('test-ai-status', 'error', 'KO', data.error || 'Erreur inconnue');
                this.addLog(`❌ IA KO - ${data.error || 'Erreur inconnue'}`, 'error');
            }
            this.consoleLog('debug', data);
        } catch (e) {
            this.setBadge('test-ai-status', 'error', 'KO', e.message);
            this.addLog(`❌ IA KO - ${e.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async testMQTT() {
        const btn = document.getElementById('test-mqtt');
        this.setBadge('test-mqtt-status', 'loading', '...');
        if (btn) btn.disabled = true;
        try {
            this.addLog('📡 Test MQTT: démarrage...', 'info');
            const res = await this.fetchWithTimeout('/api/admin/mqtt_test', { timeout: 5000 });
            const data = await res.json();
            if (data.success && data.status) {
                const s = data.status;
                if (s.connected) {
                    this.setBadge('test-mqtt-status', 'ok', 'OK', `${s.broker}:${s.port}`);
                    this.addLog(`✅ MQTT OK - ${s.broker}:${s.port} (prefix: ${s.topic_prefix || 'iaction'})`, 'success');
                } else {
                    this.setBadge('test-mqtt-status', 'error', 'KO', `${s.broker}:${s.port}`);
                    this.addLog(`❌ MQTT KO - non connecté à ${s.broker}:${s.port}`, 'error');
                }
                this.consoleLog('debug', s);
            } else {
                this.setBadge('test-mqtt-status', 'error', 'KO', data.error || 'Erreur inconnue');
                this.addLog(`❌ MQTT KO - ${data.error || 'Erreur inconnue'}`, 'error');
            }
        } catch (e) {
            this.setBadge('test-mqtt-status', 'error', 'KO', e.message);
            this.addLog(`❌ MQTT KO - ${e.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    async testRTSP() {
        const btn = document.getElementById('test-rtsp');
        this.setBadge('test-rtsp-status', 'loading', '...');
        if (btn) btn.disabled = true;
        try {
            this.addLog('🎥 Test RTSP: démarrage...', 'info');
            const urlField = document.getElementById('default_rtsp_url');
            const body = urlField && urlField.value ? { url: urlField.value } : {};
            const res = await this.fetchWithTimeout('/api/admin/rtsp_test', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                timeout: 7000
            });
            const data = await res.json();
            if (data.success) {
                const status = (data.status || '').toLowerCase();
                if (status === 'online') this.setBadge('test-rtsp-status', 'ok', 'ONLINE', data.url || '');
                else if (status === 'not_configured') this.setBadge('test-rtsp-status', 'info', 'N/C', 'URL non configurée');
                else if (status === 'offline') this.setBadge('test-rtsp-status', 'error', 'OFFLINE', data.url || '');
                else this.setBadge('test-rtsp-status', 'error', 'ERROR', data.url || '');
                this.addLog(`RTSP (${data.url || '-'}) → statut: ${data.status}`, status === 'online' ? 'success' : (status === 'not_configured' ? 'warning' : 'error'));
            } else {
                this.setBadge('test-rtsp-status', 'error', 'KO', data.error || 'Erreur inconnue');
                this.addLog(`❌ RTSP KO - ${data.error || 'Erreur inconnue'}`, 'error');
            }
            this.consoleLog('debug', data);
        } catch (e) {
            this.setBadge('test-rtsp-status', 'error', 'KO', e.message);
            this.addLog(`❌ RTSP KO - ${e.message}`, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    addLog(message, type = 'info') {
        // UI logs supprimés: sortie console uniquement selon niveau
        if (!this.shouldLog(type)) return;
        this.consoleLog(type, message);
    }

    initLogLevelFromUrl() {
        try {
            const p = new URLSearchParams(window.location.search);
            if (p.has('log')) {
                const lvl = (p.get('log') || '').toLowerCase();
                if (lvl in this.logLevels) localStorage.setItem('ADMIN_LOG_LEVEL', lvl);
            }
            const stored = (localStorage.getItem('ADMIN_LOG_LEVEL') || 'info').toLowerCase();
            this.logLevel = stored in this.logLevels ? stored : 'info';
        } catch (_) {
            this.logLevel = 'info';
        }
    }

    applyLogLevelToUi() {
        const logSelect = document.getElementById('log-level-select');
        if (logSelect) {
            logSelect.value = this.logLevel;
        }
    }

    shouldLog(type) {
        const lvl = this.logLevels[(type || 'info').toLowerCase()] ?? 2;
        const current = this.logLevels[this.logLevel] ?? 2;
        return lvl <= current;
    }

    consoleLog(type, message) {
        const styles = {
            success: 'color: #198754;',
            info: 'color: #0dcaf0;',
            warning: 'color: #ffc107;',
            error: 'color: #dc3545;',
            debug: 'color: #6c757d;'
        };
        const style = styles[type] || '';
        const prefix = '[IAction Admin]';
        const line = `%c${prefix} ${type.toUpperCase()}:`;
        if (type === 'error') console.error(line, style, message);
        else if (type === 'warning') console.warn(line, style, message);
        else if (type === 'debug') console.debug(line, style, message);
        else console.log(line, style, message);
    }
}

// Initialiser l'application d'administration
document.addEventListener('DOMContentLoaded', () => {
    new AdminApp();
});
