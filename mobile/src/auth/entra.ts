import * as AuthSession from 'expo-auth-session';
import * as SecureStore from 'expo-secure-store';
import * as WebBrowser from 'expo-web-browser';
import { Platform } from 'react-native';
import { useEffect, useState } from 'react';

WebBrowser.maybeCompleteAuthSession();

const ACCESS_TOKEN_KEY = 'habitat-entra-access-token';
const clientId = process.env.EXPO_PUBLIC_ENTRA_CLIENT_ID;
const issuer = process.env.EXPO_PUBLIC_ENTRA_ISSUER_URL;
const apiScope = process.env.EXPO_PUBLIC_ENTRA_API_SCOPE;
const unconfiguredDiscovery = {
  authorizationEndpoint: 'https://invalid.example/authorize',
};

async function saveAccessToken(accessToken: string): Promise<void> {
  if (Platform.OS === 'web') {
    sessionStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
    return;
  }
  await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken);
}

export function useEntraAuthentication() {
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const configured = Boolean(clientId && issuer && apiScope);
  const redirectUri = AuthSession.makeRedirectUri({ scheme: 'habitatinspector' });
  const discovery = AuthSession.useAutoDiscovery(
    configured && issuer ? issuer : unconfiguredDiscovery,
  );
  const [request, response, promptAsync] = AuthSession.useAuthRequest(
    {
      clientId: clientId ?? 'unconfigured-client',
      redirectUri,
      responseType: AuthSession.ResponseType.Code,
      usePKCE: true,
      scopes: ['openid', 'profile', 'offline_access', apiScope ?? 'unconfigured.scope'],
    },
    discovery,
  );

  useEffect(() => {
    async function exchangeAuthorizationCode() {
      if (response?.type !== 'success' || !clientId || !discovery?.tokenEndpoint || !request?.codeVerifier) {
        return;
      }
      try {
        const token = await AuthSession.exchangeCodeAsync(
          {
            clientId,
            code: response.params.code,
            redirectUri,
            extraParams: { code_verifier: request.codeVerifier },
          },
          discovery,
        );
        await saveAccessToken(token.accessToken);
        setAccessToken(token.accessToken);
      } catch {
        setErrorMessage('Microsoft Entra sign-in could not be completed. Try again or contact your administrator.');
      }
    }

    void exchangeAuthorizationCode();
  }, [clientId, discovery, redirectUri, request?.codeVerifier, response]);

  async function signIn() {
    if (!configured || !request) {
      setErrorMessage('Microsoft Entra sign-in is not configured for this build.');
      return;
    }
    setErrorMessage(null);
    await promptAsync();
  }

  return { accessToken, configured, errorMessage, signIn };
}
