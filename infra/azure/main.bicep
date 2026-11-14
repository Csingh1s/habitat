@description('Azure region for the staging deployment.')
param location string = resourceGroup().location

@description('Container Apps environment name.')
param containerAppsEnvironmentName string = 'habitat-inspector-staging'

@description('External-facing FastAPI Container App name.')
param containerAppName string = 'habitat-api-staging'

@description('A registry image that Azure Container Apps can pull, for example ghcr.io/OWNER/habitat-api:staging.')
param containerImage string

@description('Existing Key Vault name containing the six required staging secrets.')
param keyVaultName string

@description('Microsoft Entra External ID issuer URL from the API registration metadata.')
param oidcIssuerUrl string

@description('Microsoft Entra API application ID URI, for example api://<application-client-id>.')
param oidcAudience string

@description('Microsoft Entra External ID JWKS URL from the OpenID Connect discovery document.')
param oidcJwksUrl string

@description('Qwen Cloud Singapore OpenAI-compatible chat-completions endpoint.')
param qwenCloudInferenceUrl string = 'https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1/chat/completions'

@description('CORS origin for a browser staging client. Native mobile apps do not use CORS.')
param browserCorsOrigin string = 'https://staging.example.com'

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource containerAppsEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: containerAppsEnvironmentName
  location: location
  properties: {}
}

resource containerApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerAppsEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
      }
      secrets: [
        {
          name: 'supabase-url'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/supabase-url'
          identity: 'system'
        }
        {
          name: 'supabase-service-role-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/supabase-service-role-key'
          identity: 'system'
        }
        {
          name: 'dashscope-api-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/dashscope-api-key'
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'habitat-api'
          image: containerImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            { name: 'APP_ENV', value: 'staging' }
            { name: 'PERSISTENCE_BACKEND', value: 'supabase' }
            { name: 'SUPABASE_URL', secretRef: 'supabase-url' }
            { name: 'SUPABASE_SERVICE_ROLE_KEY', secretRef: 'supabase-service-role-key' }
            { name: 'SUPABASE_STORAGE_BUCKET', value: 'inspection-evidence' }
            { name: 'INFERENCE_PROVIDER', value: 'qwen_cloud' }
            { name: 'ENABLE_REMOTE_INFERENCE', value: 'true' }
            { name: 'DASHSCOPE_API_KEY', secretRef: 'dashscope-api-key' }
            { name: 'QWEN_CLOUD_INFERENCE_URL', value: qwenCloudInferenceUrl }
            { name: 'QWEN_CLOUD_MODEL_ID', value: 'qwen3.7-flash' }
            { name: 'QWEN_CLOUD_MODEL_VERSION', value: 'qwen-cloud-managed' }
            { name: 'OIDC_ISSUER_URL', value: oidcIssuerUrl }
            { name: 'OIDC_AUDIENCE', value: oidcAudience }
            { name: 'OIDC_JWKS_URL', value: oidcJwksUrl }
            { name: 'BROWSER_CORS_ORIGIN', value: browserCorsOrigin }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: {
                path: '/health'
                port: 8000
              }
              initialDelaySeconds: 5
              periodSeconds: 10
              failureThreshold: 18
            }
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/health'
                port: 8000
              }
              periodSeconds: 10
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 3
      }
    }
  }
}

resource keyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, containerApp.id, '4633458b-17de-408a-b874-0445c86b69e6')
  scope: keyVault
  properties: {
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
  }
}

output apiUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
