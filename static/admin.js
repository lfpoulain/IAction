class AdminApp {
    constructor() {
        this.initializeEventListeners();
        this.loadConfiguration();
        this.setupFormValidation();
    }

    initializeEventListeners() {
        // Soumission du formulaire
        document.getElementById('config-form').addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveConfiguration();
        });

        // Bouton recharger
        document.getElementById('reload-config').addEventListener('click', () => {
            this.loadConfiguration();
        });

        // Bouton redémarrer
        document.getElementById('restart-app').addEventListener('click', () => {
            this.restartApplication();
        });

        // Changement du mode API pour afficher/masquer les sections
        document.getElementById('ai_api_mode').addEventListener('change', (e) => {
            this.toggleApiSections(e.target.value);
        });
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
        
        if (field.type === 'url' && field.value && !this.isValidUrl(field.value)) {
            field.classList.add('is-invalid');
            return false;
        }
        
        if (field.type === 'number' && field.value && (field.value < field.min || field.value > field.max)) {
            field.classList.add('is-invalid');
            return false;
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
        
        if (mode === 'openai') {
            openaiSection.style.display = 'block';
            lmstudioSection.style.display = 'none';
        } else {
            openaiSection.style.display = 'none';
            lmstudioSection.style.display = 'block';
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
            this.populateForm(config);
            this.toggleApiSections(config.AI_API_MODE || 'lmstudio');
            
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
                this.addLog('⚠️ Redémarrez l\'application pour appliquer les changements', 'warning');
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
            
            const response = await fetch('/api/admin/restart', {
                method: 'POST'
            });
            
            if (response.ok) {
                this.addLog('✅ Redémarrage initié', 'success');
                this.addLog('⏳ L\'application va redémarrer dans quelques secondes...', 'info');
                
                // Rediriger vers la page d'accueil après quelques secondes
                setTimeout(() => {
                    window.location.href = '/';
                }, 3000);
            } else {
                throw new Error(`Erreur HTTP: ${response.status}`);
            }
            
        } catch (error) {
            this.addLog(`❌ Erreur lors du redémarrage: ${error.message}`, 'error');
            console.error('Erreur lors du redémarrage:', error);
        }
    }

    addLog(message, type = 'info') {
        const logsContainer = document.getElementById('config-logs');
        const timestamp = new Date().toLocaleTimeString();
        
        const logEntry = document.createElement('div');
        logEntry.className = `log-entry log-${type}`;
        
        let colorClass = '';
        switch (type) {
            case 'success':
                colorClass = 'text-success';
                break;
            case 'error':
                colorClass = 'text-danger';
                break;
            case 'warning':
                colorClass = 'text-warning';
                break;
            case 'info':
            default:
                colorClass = 'text-info';
                break;
        }
        
        logEntry.innerHTML = `<span class="text-muted">[${timestamp}]</span> <span class="${colorClass}">${message}</span>`;
        
        logsContainer.appendChild(logEntry);
        logsContainer.scrollTop = logsContainer.scrollHeight;
        
        // Limiter le nombre de logs affichés
        const logs = logsContainer.querySelectorAll('.log-entry');
        if (logs.length > 100) {
            logs[0].remove();
        }
    }
}

// Initialiser l'application d'administration
document.addEventListener('DOMContentLoaded', () => {
    new AdminApp();
});
