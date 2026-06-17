module.exports = {
    flowFile: 'flows.json',
    credentialSecret: false,
    flowFilePretty: true,
    uiPort: process.env.PORT || 1880,
    diagnostics: {
        enabled: true,
        ui: true,
    },
    runtimeState: {
        enabled: false,
        ui: false,
    },
    logging: {
        console: {
            level: "info",
            metrics: false,
            audit: false
        }
    },
    exportGlobalContextKeys: false,
    externalModules: {
        autoInstall: true,
        palette: {
            allowInstall: true,
            allowUpdate: true,
            allowUpload: false
        }
    },
    editorTheme: {
        projects: {
            enabled: false
        }
    }
};
