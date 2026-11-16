import { CameraView, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import * as Crypto from 'expo-crypto';
import { File } from 'expo-file-system';
import * as SecureStore from 'expo-secure-store';
import {
  AudioModule,
  RecordingPresets,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Alert,
  Image,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  ActivityIndicator,
} from 'react-native';
import {
  configureAuthenticatedApiSession,
  type AnalysisJob,
  type CapturedEvidence,
  fetchAssignedInspections,
  HabitatApiError,
  type InspectionCategory,
  type Inspection,
  onboardWorkspace,
  selectInspectionForCapture,
  signInDevelopmentAccount,
  submitEvidenceForAnalysis,
  transcribeVoiceNote,
} from './src/api/habitatApi';
import { useEntraAuthentication } from './src/auth/entra';

type AppTab = 'today' | 'capture' | 'review';
type AuthMode = 'signIn' | 'register';
type InspectionSection =
  | 'Roofing'
  | 'Exterior'
  | 'Structure'
  | 'Electrical'
  | 'Heating'
  | 'Cooling'
  | 'Insulation'
  | 'Plumbing'
  | 'Interior';

const sections: InspectionSection[] = [
  'Roofing',
  'Exterior',
  'Structure',
  'Electrical',
  'Heating',
  'Cooling',
  'Insulation',
  'Plumbing',
  'Interior',
];

const categoryBySection: Record<InspectionSection, InspectionCategory> = {
  Roofing: 'roofing',
  Exterior: 'exterior',
  Structure: 'structure',
  Electrical: 'electrical',
  Heating: 'heating',
  Cooling: 'cooling',
  Insulation: 'insulation',
  Plumbing: 'plumbing',
  Interior: 'interior',
};

const regionsByCountry = {
  'United States': [
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut',
    'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa',
    'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts', 'Michigan',
    'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire',
    'New Jersey', 'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio',
    'Oklahoma', 'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota',
    'Tennessee', 'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia',
    'Wisconsin', 'Wyoming',
  ],
  Canada: [
    'Alberta', 'British Columbia', 'Manitoba', 'New Brunswick', 'Newfoundland and Labrador',
    'Northwest Territories', 'Nova Scotia', 'Nunavut', 'Ontario', 'Prince Edward Island',
    'Quebec', 'Saskatchewan', 'Yukon',
  ],
} as const;

const DEMO_SESSION_KEY = 'habitat-demo-workspace';
const MAX_VOICE_NOTE_SECONDS = 300;

function formatRecordingDuration(durationMillis: number): string {
  const totalSeconds = Math.floor(durationMillis / 1000);
  return `${Math.floor(totalSeconds / 60)}:${String(totalSeconds % 60).padStart(2, '0')}`;
}

function supportedContentType(
  value: string | null | undefined,
  fileName: string,
): CapturedEvidence['contentType'] | null {
  if (value === 'image/jpeg' || value === 'image/png' || value === 'image/webp') {
    return value;
  }

  const extension = fileName.split('.').pop()?.toLowerCase();
  if (extension === 'jpg' || extension === 'jpeg') {
    return 'image/jpeg';
  }
  if (extension === 'png') {
    return 'image/png';
  }
  if (extension === 'webp') {
    return 'image/webp';
  }
  return null;
}

type VoiceNoteComposerProps = {
  value: string;
  onChangeText: (value: string) => void;
  disabled: boolean;
  hasInspection: boolean;
};

function VoiceNoteComposer({ value, onChangeText, disabled, hasInspection }: VoiceNoteComposerProps) {
  const audioRecorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const audioRecorderState = useAudioRecorderState(audioRecorder);
  const [voiceNoteState, setVoiceNoteState] = useState<'idle' | 'recording' | 'transcribing'>('idle');
  const [voiceNoteError, setVoiceNoteError] = useState<string | null>(null);
  const voiceLimitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const voiceFinalizing = useRef(false);

  useEffect(() => () => {
    if (voiceLimitTimer.current) clearTimeout(voiceLimitTimer.current);
  }, []);

  async function finishVoiceNote() {
    if (voiceFinalizing.current) return;
    voiceFinalizing.current = true;
    setVoiceNoteState('transcribing');
    setVoiceNoteError(null);
    if (voiceLimitTimer.current) clearTimeout(voiceLimitTimer.current);
    let recordingUri: string | null = audioRecorder.uri;
    try {
      await audioRecorder.stop();
      recordingUri = audioRecorder.uri ?? recordingUri;
      const durationSeconds = audioRecorder.getStatus().durationMillis / 1000;
      if (!recordingUri) throw new Error('The recording could not be read. Please record the note again.');
      const transcript = await transcribeVoiceNote(recordingUri, durationSeconds);
      const currentNote = value.trim();
      const combinedNote = currentNote ? `${currentNote}\n${transcript.text}` : transcript.text;
      if (combinedNote.length > 1000) {
        throw new Error('The transcript is too long for this note. Shorten the existing note and try again.');
      }
      onChangeText(combinedNote);
    } catch (error) {
      setVoiceNoteError(error instanceof Error ? error.message : 'Transcription failed. Please try again.');
    } finally {
      if (recordingUri) {
        try {
          new File(recordingUri).delete();
        } catch {
          setVoiceNoteError((current) => current ?? 'Temporary audio could not be removed from this device.');
        }
      }
      await setAudioModeAsync({ allowsRecording: false }).catch(() => undefined);
      setVoiceNoteState('idle');
      voiceFinalizing.current = false;
    }
  }

  async function toggleVoiceNote() {
    if (voiceNoteState === 'recording') {
      await finishVoiceNote();
      return;
    }
    if (voiceNoteState !== 'idle' || disabled) return;
    if (!hasInspection) {
      setVoiceNoteError('Select an inspection before recording a voice note.');
      return;
    }
    try {
      const permission = await AudioModule.requestRecordingPermissionsAsync();
      if (!permission.granted) {
        setVoiceNoteError('Microphone access is required to record a voice note.');
        return;
      }
      await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      await audioRecorder.prepareToRecordAsync();
      audioRecorder.record({ forDuration: MAX_VOICE_NOTE_SECONDS });
      setVoiceNoteError(null);
      setVoiceNoteState('recording');
      voiceLimitTimer.current = setTimeout(() => { void finishVoiceNote(); }, MAX_VOICE_NOTE_SECONDS * 1000);
    } catch (error) {
      setVoiceNoteError(error instanceof Error ? error.message : 'The microphone could not start.');
      await setAudioModeAsync({ allowsRecording: false }).catch(() => undefined);
    }
  }

  return (
    <>
      <View style={styles.noteComposer}>
        <TextInput
          value={value}
          maxLength={1000}
          editable={!disabled && voiceNoteState === 'idle'}
          onChangeText={onChangeText}
          placeholder="Add a note or dictate an observation..."
          placeholderTextColor="#87958F"
          multiline
          style={styles.noteInput}
          textAlignVertical="top"
        />
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={voiceNoteState === 'recording' ? 'Stop recording and transcribe' : 'Start voice recording'}
          accessibilityHint={Platform.OS === 'web' ? 'Voice recording is available in the Android or iOS app.' : 'Records up to five minutes and inserts the transcript into this editable note.'}
          accessibilityState={{ disabled: Platform.OS === 'web' || disabled || voiceNoteState === 'transcribing' || !hasInspection }}
          disabled={Platform.OS === 'web' || disabled || voiceNoteState === 'transcribing' || !hasInspection}
          onPress={() => { void toggleVoiceNote(); }}
          style={[styles.voiceButton, voiceNoteState === 'recording' && styles.voiceButtonRecording, voiceNoteState === 'transcribing' && styles.voiceButtonBusy, Platform.OS === 'web' && styles.voiceButtonWeb]}
        >
          {voiceNoteState === 'transcribing' ? (
            <ActivityIndicator size="small" color="#FFFFFF" />
          ) : (
            <Text style={styles.voiceButtonIcon}>{voiceNoteState === 'recording' ? '■' : '🎙'}</Text>
          )}
        </Pressable>
      </View>
      {Platform.OS === 'web' ? (
        <Text style={styles.voiceWebNotice}>Recording is available in the Android or iOS app.</Text>
      ) : (
        <Text style={styles.voicePrivacyNote}>
          {process.env.EXPO_PUBLIC_HABITAT_API_MODE === 'development'
            ? 'Local development blocks speech AI. Transcription needs a provider-enabled API.'
            : 'Voice is sent to Alibaba for transcription. Review the text before saving.'}
        </Text>
      )}
      {Platform.OS !== 'web' && voiceNoteState === 'recording' ? (
        <Text style={styles.voiceStatus}>Recording voice note · {formatRecordingDuration(audioRecorderState.durationMillis)} / 5:00</Text>
      ) : null}
      {Platform.OS !== 'web' && voiceNoteState === 'transcribing' ? (
        <Text style={styles.voiceStatus}>Transcribing. Your audio is removed from this device after the request.</Text>
      ) : null}
      {voiceNoteError ? <Text accessibilityRole="alert" style={styles.voiceError}>{voiceNoteError}</Text> : null}
    </>
  );
}

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isAuthenticationReady, setIsAuthenticationReady] = useState(false);
  const [authStorageNotice, setAuthStorageNotice] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>('signIn');
  const [companyName, setCompanyName] = useState('');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState(process.env.EXPO_PUBLIC_HABITAT_API_MODE === 'development' ? 'admin@example.com' : '');
  const [password, setPassword] = useState('');
  const [isSigningIn, setIsSigningIn] = useState(false);
  const [country, setCountry] = useState<keyof typeof regionsByCountry>('United States');
  const [region, setRegion] = useState('');
  const [regionSearch, setRegionSearch] = useState('');
  const [showRegionChoices, setShowRegionChoices] = useState(false);
  const [tab, setTab] = useState<AppTab>('today');
  const [section, setSection] = useState<InspectionSection>('Roofing');
  const [evidence, setEvidence] = useState<CapturedEvidence | null>(null);
  const [note, setNote] = useState('');
  const [analysisState, setAnalysisState] = useState<
    'idle' | 'uploading' | 'validating' | 'analyzing' | 'ready' | 'blocked' | 'failed'
  >('idle');
  const [analysisJob, setAnalysisJob] = useState<AnalysisJob | null>(null);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [assignedInspections, setAssignedInspections] = useState<Inspection[]>([]);
  const [selectedInspection, setSelectedInspection] = useState<Inspection | null>(null);
  const [inspectionsLoading, setInspectionsLoading] = useState(false);
  const [inspectionsError, setInspectionsError] = useState<string | null>(null);
  const [moreInspections, setMoreInspections] = useState(false);
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView>(null);
  const analysisAttempt = useRef<string | null>(null);
  const entra = useEntraAuthentication();
  const inspection = { address: selectedInspection?.property_address ?? 'Select an inspection' };
  const processing = ['uploading', 'validating', 'analyzing'].includes(analysisState);

  const syncLabel = useMemo(
    () => (analysisJob ? 'Photo stored in inspection' : evidence ? 'Photo not yet uploaded' : 'No pending photo'),
    [evidence, analysisJob],
  );
  const regionLabel = country === 'United States' ? 'State' : 'Province or territory';
  const filteredRegions = regionsByCountry[country].filter((item) =>
    item.toLowerCase().includes(regionSearch.toLowerCase()),
  );

  useEffect(() => {
    let active = true;

    async function restoreDemoWorkspace() {
      try {
        const demoSession = Platform.OS === 'web'
          ? globalThis.localStorage?.getItem(DEMO_SESSION_KEY)
          : await SecureStore.getItemAsync(DEMO_SESSION_KEY);
        if (active && __DEV__ && process.env.EXPO_PUBLIC_HABITAT_API_MODE === 'development' && demoSession === 'true') {
          setIsAuthenticated(true);
        }
      } catch {
        if (active) {
          setAuthStorageNotice('Your demo workspace could not be restored on this device. Sign in again to continue.');
        }
      } finally {
        if (active) {
          setIsAuthenticationReady(true);
        }
      }
    }

    void restoreDemoWorkspace();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    async function completeEntraSignIn() {
      if (!entra.accessToken) {
        return;
      }
      try {
        if (authMode === 'register') {
          await onboardWorkspace(entra.accessToken, {
            companyName,
            fullName,
            country,
            region,
          });
        }
        const inspections = await fetchAssignedInspections(entra.accessToken);
        configureAuthenticatedApiSession({
          accessToken: entra.accessToken,
          inspectionId: '',
        });
        if (inspections.length === 0) {
          setAuthStorageNotice('Your account is active, but no inspections are assigned yet. An administrator must assign one before you can upload evidence.');
        }
        setIsAuthenticated(true);
      } catch (error) {
        setAuthStorageNotice(
          error instanceof HabitatApiError || error instanceof Error
            ? error.message
            : 'Your account could not be completed. Try again or contact your administrator.',
        );
      }
    }

    void completeEntraSignIn();
  }, [authMode, companyName, country, entra.accessToken, fullName, region]);

  useEffect(() => {
    if (!isAuthenticated) return;
    let active = true;
    fetchAssignedInspections().then((rows) => {
      if (active) { setAssignedInspections(rows); setMoreInspections(rows.length === 50); setInspectionsError(null); }
    }).catch((error: unknown) => {
      if (active) setInspectionsError(error instanceof Error ? error.message : 'Inspections could not be loaded.');
    });
    return () => { active = false; };
  }, [isAuthenticated]);

  async function refreshInspections(loadMore = false) {
    if (inspectionsLoading) return;
    setInspectionsLoading(true);
    setInspectionsError(null);
    try {
      const rows = await fetchAssignedInspections(undefined, loadMore ? assignedInspections.at(-1)?.id : undefined);
      setAssignedInspections((current) => loadMore ? [...current, ...rows] : rows);
      setMoreInspections(rows.length === 50);
    } catch (error) {
      setInspectionsError(error instanceof Error ? error.message : 'Inspections could not be loaded.');
    } finally { setInspectionsLoading(false); }
  }

  function startInspection(next: Inspection) {
    if (processing) return;
    const select = () => {
      selectInspectionForCapture(next.id);
      setSelectedInspection(next);
      setEvidence(null); setNote(''); setAnalysisJob(null); setAnalysisError(null); setAnalysisState('idle');
      setTab('capture');
    };
    if (evidence && selectedInspection?.id !== next.id) {
      if (Platform.OS === 'web') {
        if (globalThis.confirm('Switch inspection and discard the current local photo?')) select();
      } else {
        Alert.alert('Switch inspection?', 'The current local photo will be discarded.', [
          { text: 'Cancel', style: 'cancel' }, { text: 'Switch', style: 'destructive', onPress: select },
        ]);
      }
      return;
    }
    if (selectedInspection?.id === next.id) { setTab('capture'); return; }
    select();
  }

  function selectCountry(nextCountry: keyof typeof regionsByCountry) {
    setCountry(nextCountry);
    setRegion('');
    setRegionSearch('');
    setShowRegionChoices(false);
  }

  async function submitAuthentication() {
    if (process.env.EXPO_PUBLIC_HABITAT_API_MODE === 'deployed') {
      if (authMode === 'register' && (!companyName.trim() || !fullName.trim() || !region)) {
        Alert.alert('Complete your profile', 'Add your company name, full name, and location before continuing.');
        return;
      }
      await entra.signIn();
      return;
    }
    if (process.env.EXPO_PUBLIC_HABITAT_API_MODE !== 'development') {
      setAuthStorageNotice('Account sign-in is not configured for this build.');
      return;
    }
    const emailLooksValid = /^\S+@\S+\.\S+$/.test(email);
    if (!emailLooksValid || password.length < 1) {
      setAuthStorageNotice('Enter the local account email and password.');
      return;
    }
    setIsSigningIn(true);
    setAuthStorageNotice(null);
    try {
      await signInDevelopmentAccount(email, password);
      setIsAuthenticated(true);
    } catch (error) {
      setAuthStorageNotice(error instanceof Error ? error.message : 'Local sign-in failed.');
    } finally {
      setIsSigningIn(false);
    }
  }

  async function enterDemoWorkspace() {
    try {
      if (Platform.OS === 'web') {
        globalThis.localStorage?.setItem(DEMO_SESSION_KEY, 'true');
      } else {
        await SecureStore.setItemAsync(DEMO_SESSION_KEY, 'true');
      }
    } catch {
      setAuthStorageNotice('Demo storage is unavailable. The workspace will be open only until this app closes.');
    }
    setIsAuthenticated(true);
  }

  function renderAuth() {
    const isRegistering = authMode === 'register';
    return (
      <SafeAreaView style={styles.authSafeArea}>
        <StatusBar style="dark" />
        <ScrollView contentContainerStyle={styles.authScrollContent} keyboardShouldPersistTaps="handled">
          <View style={styles.authBrand}>
            <View style={styles.authBrandMark}><Text style={styles.authBrandMarkText}>H</Text></View>
            <View>
              <Text style={styles.authBrandName}>HABITAT</Text>
              <Text style={styles.authBrandSubtext}>Professional inspection operations</Text>
            </View>
          </View>

          <View style={styles.authWelcome}>
            <Text style={styles.authEyebrow}>{isRegistering ? 'CREATE YOUR WORKSPACE' : 'WELCOME BACK'}</Text>
            <Text style={styles.authTitle}>{isRegistering ? 'Set up your inspection workspace' : 'Sign in to your workspace'}</Text>
            <Text style={styles.authDescription}>
              {isRegistering
                ? 'Start with your company and location. You can invite your team later.'
                : 'Manage inspection evidence and review AI-assisted drafts securely.'}
            </Text>
          </View>

          <View style={styles.authCard}>
            {isRegistering ? (
              <>
                <AuthField label="COMPANY NAME" value={companyName} onChangeText={setCompanyName} placeholder="Example: Northstar Home Inspections" />
                <AuthField label="FULL NAME" value={fullName} onChangeText={setFullName} placeholder="Your full name" />
              </>
            ) : null}
            <AuthField label="EMAIL ADDRESS" value={email} onChangeText={setEmail} placeholder="name@company.com" keyboardType="email-address" autoCapitalize="none" />
            <AuthField label="PASSWORD" value={password} onChangeText={setPassword} placeholder="At least 8 characters" secureTextEntry />

            {isRegistering ? (
              <View style={styles.locationSection}>
                <Text style={styles.authFieldLabel}>COUNTRY</Text>
                <View style={styles.countryRow}>
                  {(Object.keys(regionsByCountry) as Array<keyof typeof regionsByCountry>).map((item) => (
                    <Pressable key={item} onPress={() => selectCountry(item)} style={[styles.countryButton, country === item && styles.countryButtonSelected]}>
                      <Text style={[styles.countryButtonText, country === item && styles.countryButtonTextSelected]}>{item}</Text>
                    </Pressable>
                  ))}
                </View>
                <Text style={[styles.authFieldLabel, styles.regionLabel]}>{regionLabel.toUpperCase()}</Text>
                <Pressable onPress={() => setShowRegionChoices((visible) => !visible)} style={styles.regionSelector}>
                  <Text style={region ? styles.regionSelectorText : styles.regionPlaceholder}>{region || `Select ${regionLabel.toLowerCase()}`}</Text>
                  <Text style={styles.regionChevron}>{showRegionChoices ? '⌃' : '⌄'}</Text>
                </Pressable>
                {showRegionChoices ? (
                  <View style={styles.regionMenu}>
                    <TextInput value={regionSearch} onChangeText={setRegionSearch} placeholder={`Search ${regionLabel.toLowerCase()}`} placeholderTextColor="#87958F" style={styles.regionSearch} autoCapitalize="words" />
                    <ScrollView style={styles.regionResults} keyboardShouldPersistTaps="handled">
                      {filteredRegions.map((item) => (
                        <Pressable key={item} onPress={() => { setRegion(item); setRegionSearch(''); setShowRegionChoices(false); }} style={styles.regionOption}>
                          <Text style={styles.regionOptionText}>{item}</Text>
                        </Pressable>
                      ))}
                    </ScrollView>
                  </View>
                ) : null}
              </View>
            ) : null}

            <Pressable style={styles.authPrimaryButton} onPress={() => void submitAuthentication()} disabled={isSigningIn}>
              <Text style={styles.authPrimaryButtonText}>{isSigningIn ? 'Signing in...' : isRegistering ? 'Create workspace' : 'Sign in'}</Text>
              <Text style={styles.authPrimaryArrow}>→</Text>
            </Pressable>
            {!isRegistering ? <Text style={styles.authHelpText}>{process.env.EXPO_PUBLIC_HABITAT_API_MODE === 'development' ? 'Local development account. Microsoft sign-in remains available in deployed builds.' : 'Sign-in is secured through your organization’s Microsoft identity provider.'}</Text> : null}
            {entra.errorMessage ? <Text style={styles.authStorageNotice}>{entra.errorMessage}</Text> : null}
            <View style={styles.authDemoDivider}><View style={styles.authDemoLine} /><Text style={styles.authDemoDividerText}>DEVELOPMENT</Text><View style={styles.authDemoLine} /></View>
            <Pressable style={styles.authDemoButton} onPress={enterDemoWorkspace}>
              <Text style={styles.authDemoButtonText}>Open local demo workspace</Text>
            </Pressable>
            <Text style={styles.authDemoText}>No account or password is used. This is for local UI testing only.</Text>
            {authStorageNotice ? <Text style={styles.authStorageNotice}>{authStorageNotice}</Text> : null}
          </View>

          {process.env.EXPO_PUBLIC_HABITAT_API_MODE === 'deployed' ? <View style={styles.authSwitchRow}>
            <Text style={styles.authSwitchText}>{isRegistering ? 'Already have a workspace?' : 'New to Habitat?'}</Text>
            <Pressable onPress={() => { setAuthMode(isRegistering ? 'signIn' : 'register'); setShowRegionChoices(false); }}>
              <Text style={styles.authSwitchAction}>{isRegistering ? 'Sign in' : 'Create one'}</Text>
            </Pressable>
          </View> : null}
          <View style={styles.authSecurityRow}>
            <Text style={styles.authSecurityIcon}>✓</Text>
            <Text style={styles.authSecurityText}>Evidence stays private and every AI suggestion requires human review.</Text>
          </View>
        </ScrollView>
      </SafeAreaView>
    );
  }

  function stageEvidence(nextEvidence: CapturedEvidence) {
    setEvidence(nextEvidence);
    setAnalysisState('idle');
    setAnalysisJob(null);
    setAnalysisError(null);
    setTab('review');
  }

  async function choosePhoto() {
    if (!selectedInspection) { setTab('today'); return; }
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Photo access required', 'Allow photo access to attach inspection evidence.');
      return;
    }

    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.9,
      allowsEditing: false,
    });

    if (!result.canceled) {
      const asset = result.assets[0];
      const fileName = asset.fileName ?? `inspection-photo-${Date.now()}.jpg`;
      const contentType = supportedContentType(asset.mimeType, fileName);
      if (!contentType) {
        Alert.alert('Unsupported image type', 'Choose a JPEG, PNG, or WebP inspection photo.');
        return;
      }
      stageEvidence({
        uri: asset.uri,
        fileName,
        contentType,
        captureTimestamp: new Date().toISOString(),
      });
    }
  }

  async function queueAnalysis() {
    if (processing) return;
    if (!selectedInspection) { setAnalysisError('Select an inspection before analysis.'); setTab('today'); return; }
    if (!evidence) {
      Alert.alert('Add a photo first', 'Capture or choose an inspection photo before analysis.');
      setTab('capture');
      return;
    }
    if (!note.trim()) { setAnalysisError('Add the inspector context before sending this photo.'); return; }

    setAnalysisError(null);
    setAnalysisJob(null);
    analysisAttempt.current ??= Crypto.randomUUID();
    try {
      const job = await submitEvidenceForAnalysis(
        { ...evidence, inspectorNote: note.trim() },
        categoryBySection[section],
        setAnalysisState,
        analysisAttempt.current,
      );
      setAnalysisJob(job);
      analysisAttempt.current = null;
      setAnalysisState(job.status === 'succeeded' ? 'ready' : 'blocked');
    } catch (error) {
      setAnalysisState('failed');
      setAnalysisError(
        error instanceof HabitatApiError || error instanceof Error
          ? error.message
          : 'The evidence could not be analyzed.',
      );
    }
  }

  async function capturePhoto() {
    if (!selectedInspection || processing) return;
    const photo = await cameraRef.current?.takePictureAsync({ quality: 0.9 });
    if (!photo?.uri) {
      Alert.alert('Camera unavailable', 'Please try capturing the photo again.');
      return;
    }

    stageEvidence({
      uri: photo.uri,
      fileName: `inspection-photo-${Date.now()}.jpg`,
      contentType: 'image/jpeg',
      captureTimestamp: new Date().toISOString(),
    });
  }

  function renderToday() {
    return (
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={styles.hero}>
          <View style={styles.heroHeader}>
            <Text style={styles.heroEyebrow}>FIELD OPERATIONS</Text>
            <View style={styles.livePill}>
              <View style={styles.liveDot} />
              <Text style={styles.liveText}>ON SCHEDULE</Text>
            </View>
          </View>
          <Text style={styles.heroTitle}>Assigned inspections</Text>
          <Text style={styles.heroText}>{selectedInspection?.property_address ?? 'Select your inspection to capture evidence.'}</Text>
          <View style={styles.syncPill}>
            <View style={styles.syncDot} />
            <Text style={styles.syncText}>{syncLabel}</Text>
          </View>
          <View style={styles.heroMetrics}>
            <View style={styles.heroMetric}>
              <Text style={styles.heroMetricValue}>{assignedInspections.length}{moreInspections ? '+' : ''}</Text>
              <Text style={styles.heroMetricLabel}>ASSIGNED</Text>
            </View>
            <View style={styles.heroMetricDivider} />
            <View style={styles.heroMetric}>
              <Text style={styles.heroMetricValue}>{selectedInspection ? '1' : '0'}</Text>
              <Text style={styles.heroMetricLabel}>SELECTED</Text>
            </View>
            <View style={styles.heroMetricDivider} />
            <View style={styles.heroMetric}>
              <Text style={styles.heroMetricValue}>{evidence ? '1' : '0'}</Text>
              <Text style={styles.heroMetricLabel}>LOCAL PHOTO</Text>
            </View>
          </View>
        </View>

        <View style={styles.sectionHeader}>
          <View>
            <Text style={styles.sectionTitle}>Your inspections</Text>
            <Text style={styles.sectionSubtext}>{assignedInspections.length} loaded</Text>
          </View>
          <Pressable disabled={inspectionsLoading || processing} onPress={() => void refreshInspections()} style={styles.routeBadge}><Text style={styles.routeBadgeText}>{inspectionsLoading ? 'LOADING' : 'REFRESH'}</Text></Pressable>
        </View>
        {inspectionsError && <Text accessibilityRole="alert" style={styles.mutedText}>{inspectionsError}</Text>}
        {!assignedInspections.length && <Text style={styles.mutedText}>No assigned inspections found.</Text>}
        {assignedInspections.map((job) => <View key={job.id} style={[styles.inspectionCard, selectedInspection?.id === job.id && styles.activeInspectionCard]}>
          <View style={styles.inspectionBody}>
            <Text style={styles.inspectionAddress}>{job.property_address ?? 'Address unavailable'}</Text>
            <Text style={styles.inspectionDetails}>{job.scheduled_for ? new Date(job.scheduled_for).toLocaleString() : 'Not scheduled'} / {job.status.replaceAll('_', ' ')}</Text>
            <Text style={styles.sectionSubtext}>#{job.id.slice(0, 8)}</Text>
            <Pressable disabled={processing} style={styles.primaryButton} onPress={() => startInspection(job)}>
              <Text style={styles.primaryButtonText}>{selectedInspection?.id === job.id ? 'Continue inspection' : 'Start inspection'}</Text>
            </Pressable>
          </View>
        </View>)}
        {moreInspections && <Pressable disabled={inspectionsLoading} style={styles.textButton} onPress={() => void refreshInspections(true)}><Text style={styles.textButtonLabel}>Load more inspections</Text></Pressable>}

        <View style={styles.safetyCard}>
          <View style={styles.safetyIcon}><Text style={styles.safetyIconText}>✓</Text></View>
          <View style={styles.safetyContent}>
            <Text style={styles.safetyTitle}>Human-reviewed by design</Text>
            <Text style={styles.safetyText}>
              AI suggestions remain evidence-linked drafts. You decide every finding, severity, and recommendation.
            </Text>
          </View>
        </View>
      </ScrollView>
    );
  }

  function renderCapture() {
    if (!selectedInspection) return <View style={styles.centered}><Text style={styles.mutedText}>Select an assigned inspection first.</Text><Pressable style={styles.textButton} onPress={() => setTab('today')}><Text style={styles.textButtonLabel}>Open inspections</Text></Pressable></View>;
    if (!cameraPermission) {
      return <View style={styles.centered}><Text style={styles.mutedText}>Preparing camera…</Text></View>;
    }

    if (!cameraPermission.granted) {
      return (
        <View style={styles.permissionScreen}>
          <View style={styles.permissionIcon}><Text style={styles.permissionIconText}>◉</Text></View>
          <Text style={styles.permissionTitle}>Camera access required</Text>
          <Text style={styles.permissionText}>
            Camera access lets you capture evidence directly into the assigned inspection.
          </Text>
          <Pressable style={styles.primaryButton} onPress={requestCameraPermission}>
            <Text style={styles.primaryButtonText}>Allow camera</Text>
          </Pressable>
          <Pressable style={styles.textButton} onPress={choosePhoto}>
            <Text style={styles.textButtonLabel}>Choose from photo library</Text>
          </Pressable>
        </View>
      );
    }

    return (
      <View style={styles.captureScreen}>
        <CameraView ref={cameraRef} style={styles.camera} facing="back">
          <View style={styles.cameraOverlay}>
            <View style={styles.cameraTop}>
              <View>
                <Text style={styles.cameraLabel}>CAPTURE EVIDENCE</Text>
                <Text style={styles.cameraSubtitle}>{section}</Text>
              </View>
              <View style={styles.offlinePill}><Text style={styles.offlineText}>#{selectedInspection.id.slice(0, 8)}</Text></View>
            </View>
            <View style={styles.captureGuide}>
              <Text style={styles.captureGuideText}>Frame the full component before capturing</Text>
            </View>
          </View>
        </CameraView>

        <View style={styles.capturePanel}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
            {sections.map((item) => (
              <Pressable
                key={item}
                onPress={() => setSection(item)}
                style={[styles.chip, section === item && styles.chipSelected]}
              >
                <Text style={[styles.chipText, section === item && styles.chipTextSelected]}>{item}</Text>
              </Pressable>
            ))}
          </ScrollView>
          <View style={styles.captureActions}>
            <Pressable style={styles.galleryButton} onPress={choosePhoto}>
              <Text style={styles.galleryButtonText}>Gallery</Text>
            </Pressable>
            <Pressable style={styles.shutterButton} onPress={capturePhoto}>
              <View style={styles.shutterInner} />
            </Pressable>
            <Pressable style={styles.noteButton} onPress={() => setTab('review')}>
              <Text style={styles.noteButtonText}>Review</Text>
            </Pressable>
          </View>
        </View>
      </View>
    );
  }

  function renderReview() {
    return (
      <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
        <View style={styles.reviewHeader}>
          <Text style={styles.eyebrow}>INSPECTION EVIDENCE</Text>
          <Text style={styles.reviewTitle}>{section}</Text>
          <Text style={styles.reviewSubtext}>{inspection.address}</Text>
        </View>

        {evidence ? (
          <Image source={{ uri: evidence.uri }} style={styles.evidenceImage} resizeMode="cover" />
        ) : (
          <Pressable style={styles.emptyEvidence} onPress={() => setTab('capture')}>
            <Text style={styles.emptyEvidenceTitle}>Add an evidence photo</Text>
            <Text style={styles.emptyEvidenceText}>Capture or choose a photo to create an AI review candidate.</Text>
          </Pressable>
        )}

        <View style={styles.reviewCard}>
          <View style={styles.reviewCardTop}>
            <View>
              <Text style={styles.cardLabel}>INSPECTOR CONTEXT</Text>
              <Text style={styles.reviewCardTitle}>What did you observe?</Text>
            </View>
            <Text style={styles.requiredText}>REQUIRED</Text>
          </View>
          <VoiceNoteComposer
            value={note}
            onChangeText={setNote}
            disabled={processing || Boolean(analysisJob)}
            hasInspection={Boolean(selectedInspection)}
          />
        </View>

        <View style={styles.reviewCard}>
          <View style={styles.reviewCardTop}>
            <View>
              <Text style={styles.cardLabel}>QWEN ANALYSIS</Text>
              <Text style={styles.reviewCardTitle}>Review candidate</Text>
            </View>
            <View style={styles.reviewBadge}><Text style={styles.reviewBadgeText}>HUMAN REVIEW</Text></View>
          </View>
          {analysisState === 'uploading' || analysisState === 'validating' || analysisState === 'analyzing' ? (
            <>
              <Text style={styles.reviewBody}>
                {analysisState === 'uploading'
                  ? 'Uploading inspection evidence…'
                  : analysisState === 'validating'
                    ? 'Verifying image integrity and queueing validation…'
                    : 'Requesting a constrained Qwen review candidate…'}
              </Text>
              <View style={styles.pendingRow}>
                <View style={styles.pendingDot} />
                <Text style={styles.pendingText}>No finding has been created</Text>
              </View>
            </>
          ) : analysisState === 'ready' && analysisJob?.review_candidate ? (
            <View style={styles.candidateContent}>
              <Text style={styles.candidateTitle}>AI review candidate</Text>
              <Text style={styles.candidateCaption}>{analysisJob.review_candidate.draft_caption}</Text>
              {analysisJob.review_candidate.draft_observation ? (
                <Text style={styles.reviewBody}>{analysisJob.review_candidate.draft_observation}</Text>
              ) : null}
              <Text style={styles.candidateMeta}>
                Confidence {Math.round(analysisJob.review_candidate.confidence * 100)}% · {analysisJob.model_id}
              </Text>
              <Text style={styles.uncertaintyText}>{analysisJob.review_candidate.uncertainty_reason}</Text>
              <Text style={styles.humanReviewText}>Inspector review is required before this can become a finding.</Text>
            </View>
          ) : analysisState === 'blocked' ? (
            <>
              <Text style={styles.reviewBody}>
                The image uploaded successfully, but analysis is unavailable in this local environment.
              </Text>
              <Text style={styles.errorText}>
                {analysisJob?.error_message ?? 'Qwen inference has not been configured.'}
              </Text>
              <Text style={styles.uncertaintyText}>
                No issue, safety condition, or report finding was created.
              </Text>
            </>
          ) : analysisState === 'failed' ? (
            <>
              <Text style={styles.errorText}>{analysisError ?? 'The analysis request failed.'}</Text>
              <Pressable style={styles.analyzeButton} onPress={queueAnalysis}>
                <Text style={styles.analyzeButtonText}>Try again</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Text style={styles.reviewBody}>
                Analysis has not been run. Results will always be a draft and cannot be published without your approval.
              </Text>
              <Pressable style={styles.analyzeButton} onPress={queueAnalysis}>
                <Text style={styles.analyzeButtonText}>Analyze photo</Text>
              </Pressable>
            </>
          )}
        </View>

        <View style={styles.reviewActions}>
          <Pressable style={styles.secondaryButton} onPress={() => setTab('capture')}>
            <Text style={styles.secondaryButtonText}>Add another photo</Text>
          </Pressable>
          <Pressable
            style={styles.primaryButton}
            onPress={() =>
              Alert.alert(
                evidence ? 'Evidence ready' : 'Add a photo first',
                evidence
                  ? 'Use Analyze photo to upload this evidence through the secure API flow.'
                  : 'Capture or choose a photo before saving inspection evidence.',
              )
            }
          >
            <Text style={styles.primaryButtonText}>Save evidence</Text>
          </Pressable>
        </View>
      </ScrollView>
    );
  }

  if (!isAuthenticationReady) {
    return (
      <SafeAreaView style={styles.authSafeArea}>
        <StatusBar style="dark" />
        <View style={styles.authLoading}><Text style={styles.authLoadingText}>Opening workspace…</Text></View>
      </SafeAreaView>
    );
  }

  if (!isAuthenticated) {
    return renderAuth();
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <StatusBar style="dark" />
      <View style={styles.appShell}>
        <View style={styles.topBar}>
          <View style={styles.brandMark}><Text style={styles.brandMarkText}>H</Text></View>
          <View>
            <Text style={styles.brandName}>HABITAT</Text>
            <View style={styles.workspaceRow}>
              <View style={styles.workspaceDot} />
              <Text style={styles.brandSubtext}>Inspection workspace</Text>
            </View>
          </View>
          <View style={styles.profileAvatar}><Text style={styles.profileAvatarText}>A</Text></View>
        </View>

        <View style={styles.content}>
          {tab === 'today' && renderToday()}
          {tab === 'capture' && renderCapture()}
          {tab === 'review' && renderReview()}
        </View>

        <View style={styles.tabBar}>
          <TabButton active={tab === 'today'} label="Today" icon="◼" onPress={() => setTab('today')} />
          <TabButton active={tab === 'capture'} label="Capture" icon="◉" onPress={() => setTab('capture')} />
          <TabButton active={tab === 'review'} label="Review" icon="✓" onPress={() => setTab('review')} />
        </View>
      </View>
    </SafeAreaView>
  );
}

function AuthField({
  label,
  ...inputProps
}: { label: string } & React.ComponentProps<typeof TextInput>) {
  return (
    <View style={styles.authField}>
      <Text style={styles.authFieldLabel}>{label}</Text>
      <TextInput
        {...inputProps}
        placeholderTextColor="#87958F"
        style={styles.authInput}
      />
    </View>
  );
}

function TabButton({ active, icon, label, onPress }: { active: boolean; icon: string; label: string; onPress: () => void }) {
  return (
    <Pressable onPress={onPress} style={styles.tabButton}>
      <Text style={[styles.tabIcon, active && styles.tabIconActive]}>{icon}</Text>
      <Text style={[styles.tabLabel, active && styles.tabLabelActive]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  authSafeArea: { flex: 1, backgroundColor: '#FFFFFF' },
  authScrollContent: { flexGrow: 1, padding: 24, paddingTop: 36, paddingBottom: 34 },
  authBrand: { flexDirection: 'row', alignItems: 'center' },
  authBrandMark: { width: 42, height: 42, borderRadius: 13, backgroundColor: '#0F5D4E', alignItems: 'center', justifyContent: 'center', marginRight: 11 },
  authBrandMarkText: { color: '#FFFFFF', fontSize: 17, fontWeight: '700' },
  authBrandName: { color: '#18312A', fontSize: 14, fontWeight: '700', letterSpacing: 1.5 },
  authBrandSubtext: { color: '#66756F', fontSize: 11, marginTop: 2 },
  authWelcome: { marginTop: 46, marginBottom: 25 },
  authEyebrow: { color: '#167A63', fontSize: 10, fontWeight: '700', letterSpacing: 1 },
  authTitle: { color: '#18312A', fontSize: 21, lineHeight: 27, fontWeight: '700', marginTop: 10, maxWidth: 290 },
  authDescription: { color: '#62736B', fontSize: 13, lineHeight: 19, marginTop: 9, maxWidth: 340 },
  authCard: { backgroundColor: '#FFFFFF', borderWidth: 1, borderColor: '#E2EAE5', borderRadius: 18, padding: 17, boxShadow: '0px 8px 20px rgba(24, 49, 42, 0.06)' },
  authField: { marginBottom: 15 },
  authFieldLabel: { color: '#648177', fontSize: 9, fontWeight: '700', letterSpacing: 0.8, marginBottom: 7 },
  authInput: { height: 44, color: '#18312A', fontSize: 13, borderRadius: 10, borderWidth: 1, borderColor: '#D5E2DB', backgroundColor: '#FFFFFF', paddingHorizontal: 12 },
  locationSection: { marginTop: 1 },
  countryRow: { flexDirection: 'row', gap: 8, marginBottom: 15 },
  countryButton: { flex: 1, minHeight: 40, alignItems: 'center', justifyContent: 'center', borderRadius: 10, borderWidth: 1, borderColor: '#D5E2DB', backgroundColor: '#FFFFFF' },
  countryButtonSelected: { backgroundColor: '#E8F5F0', borderColor: '#9CCFB9' },
  countryButtonText: { color: '#66756F', fontSize: 12, fontWeight: '600' },
  countryButtonTextSelected: { color: '#0F5D4E', fontWeight: '700' },
  regionLabel: { marginTop: 1 },
  regionSelector: { minHeight: 44, borderRadius: 10, borderWidth: 1, borderColor: '#D5E2DB', paddingHorizontal: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: '#FFFFFF' },
  regionSelectorText: { color: '#18312A', fontSize: 13 },
  regionPlaceholder: { color: '#87958F', fontSize: 13 },
  regionChevron: { color: '#167A63', fontSize: 18, lineHeight: 18 },
  regionMenu: { marginTop: 7, borderRadius: 10, borderWidth: 1, borderColor: '#CDE6DB', backgroundColor: '#F7FCF9', overflow: 'hidden' },
  regionSearch: { height: 40, borderBottomWidth: 1, borderBottomColor: '#D5E2DB', color: '#18312A', fontSize: 13, paddingHorizontal: 11, backgroundColor: '#FFFFFF' },
  regionResults: { maxHeight: 146 },
  regionOption: { minHeight: 38, justifyContent: 'center', paddingHorizontal: 11, borderBottomWidth: 1, borderBottomColor: '#E7F0EA' },
  regionOptionText: { color: '#365347', fontSize: 13 },
  authPrimaryButton: { marginTop: 19, minHeight: 46, borderRadius: 11, backgroundColor: '#167A63', flexDirection: 'row', alignItems: 'center', justifyContent: 'center' },
  authPrimaryButtonText: { color: '#FFFFFF', fontSize: 13, fontWeight: '700' },
  authPrimaryArrow: { color: '#D3F2E2', fontSize: 18, marginLeft: 8, marginTop: -1 },
  authHelpText: { color: '#73827B', fontSize: 10, lineHeight: 15, textAlign: 'center', marginTop: 13, paddingHorizontal: 8 },
  authDemoDivider: { flexDirection: 'row', alignItems: 'center', marginTop: 18 },
  authDemoLine: { height: 1, backgroundColor: '#E4ECE7', flex: 1 },
  authDemoDividerText: { color: '#87958F', fontSize: 9, fontWeight: '700', letterSpacing: 0.8, marginHorizontal: 9 },
  authDemoButton: { minHeight: 42, borderRadius: 10, borderWidth: 1, borderColor: '#B9D7CA', backgroundColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center', marginTop: 13 },
  authDemoButtonText: { color: '#0F5D4E', fontSize: 12, fontWeight: '700' },
  authDemoText: { color: '#73827B', fontSize: 10, lineHeight: 15, textAlign: 'center', marginTop: 8, paddingHorizontal: 8 },
  authStorageNotice: { color: '#9A681A', fontSize: 10, lineHeight: 15, textAlign: 'center', marginTop: 9, paddingHorizontal: 8 },
  authSwitchRow: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', marginTop: 21 },
  authSwitchText: { color: '#66756F', fontSize: 12 },
  authSwitchAction: { color: '#167A63', fontSize: 12, fontWeight: '700', marginLeft: 6 },
  authSecurityRow: { marginTop: 'auto', paddingTop: 30, flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'center', paddingHorizontal: 15 },
  authSecurityIcon: { color: '#167A63', fontSize: 13, fontWeight: '700', marginRight: 7 },
  authSecurityText: { color: '#73827B', fontSize: 10, lineHeight: 15, flex: 1 },
  authLoading: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  authLoadingText: { color: '#66756F', fontSize: 13 },
  safeArea: { flex: 1, backgroundColor: '#FFFFFF' },
  appShell: { flex: 1, backgroundColor: '#FFFFFF' },
  topBar: { height: 72, backgroundColor: '#FFFFFF', flexDirection: 'row', alignItems: 'center', paddingHorizontal: 20, borderBottomWidth: 1, borderBottomColor: '#E4ECE7', boxShadow: '0px 2px 10px rgba(24, 49, 42, 0.04)' },
  brandMark: { width: 40, height: 40, backgroundColor: '#0F5D4E', borderRadius: 13, alignItems: 'center', justifyContent: 'center', marginRight: 11 },
  brandMarkText: { color: '#FFFFFF', fontSize: 16, fontWeight: '700' },
  brandName: { color: '#18312A', fontSize: 14, fontWeight: '700', letterSpacing: 1.4 },
  workspaceRow: { flexDirection: 'row', alignItems: 'center', marginTop: 2 },
  workspaceDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: '#167A63', marginRight: 5 },
  brandSubtext: { color: '#66756F', fontSize: 11, fontWeight: '600' },
  profileAvatar: { marginLeft: 'auto', width: 38, height: 38, borderRadius: 19, backgroundColor: '#E8F5F0', justifyContent: 'center', alignItems: 'center', borderWidth: 1, borderColor: '#CDE6DB' },
  profileAvatarText: { color: '#0F5D4E', fontWeight: '700', fontSize: 13 },
  content: { flex: 1 },
  scrollContent: { padding: 20, paddingBottom: 108 },
  hero: { backgroundColor: '#0F5D4E', padding: 20, borderRadius: 22, marginBottom: 25, overflow: 'hidden', boxShadow: '0px 12px 26px rgba(15, 93, 78, 0.16)' },
  heroHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  heroEyebrow: { color: '#C8E8DB', fontSize: 9, fontWeight: '700', letterSpacing: 1.1 },
  livePill: { flexDirection: 'row', alignItems: 'center', backgroundColor: 'rgba(255,255,255,0.10)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.12)', paddingHorizontal: 9, paddingVertical: 6, borderRadius: 20 },
  liveDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: '#90E0C1', marginRight: 6 },
  liveText: { color: '#E5F8EF', fontSize: 8, fontWeight: '700', letterSpacing: 0.6 },
  eyebrow: { color: '#55756A', fontSize: 9, fontWeight: '700', letterSpacing: 1 },
  heroTitle: { color: '#FFFFFF', fontSize: 20, lineHeight: 25, fontWeight: '700', marginTop: 12, letterSpacing: 0 },
  heroText: { color: '#D0E8DE', fontSize: 12, lineHeight: 17, marginTop: 5, maxWidth: '90%' },
  syncPill: { alignSelf: 'flex-start', marginTop: 17, flexDirection: 'row', alignItems: 'center', backgroundColor: '#146B58', borderRadius: 20, paddingVertical: 8, paddingHorizontal: 11 },
  syncDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: '#90E0C1', marginRight: 7 },
  syncText: { color: '#E4F6EE', fontSize: 11, fontWeight: '700' },
  heroMetrics: { marginTop: 19, paddingTop: 14, borderTopWidth: 1, borderTopColor: 'rgba(255,255,255,0.12)', flexDirection: 'row', alignItems: 'center' },
  heroMetric: { flex: 1 },
  heroMetricValue: { color: '#FFFFFF', fontSize: 14, fontWeight: '700' },
  heroMetricLabel: { color: '#B8DACC', fontSize: 8, fontWeight: '700', letterSpacing: 0.5, marginTop: 3 },
  heroMetricDivider: { width: 1, height: 30, backgroundColor: 'rgba(255,255,255,0.14)', marginHorizontal: 9 },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 13 },
  sectionTitle: { color: '#18312A', fontSize: 16, fontWeight: '700', letterSpacing: 0 },
  sectionSubtext: { color: '#66756F', fontSize: 11, marginTop: 3, fontWeight: '400' },
  sectionMeta: { color: '#66756F', fontSize: 13 },
  routeBadge: { backgroundColor: '#E8F5F0', paddingHorizontal: 10, paddingVertical: 7, borderRadius: 10 },
  routeBadgeText: { color: '#167A63', fontSize: 9, fontWeight: '700', letterSpacing: 0.5 },
  inspectionCard: { backgroundColor: '#FFFFFF', borderRadius: 18, padding: 16, flexDirection: 'row', marginBottom: 13, borderWidth: 1, borderColor: '#E2EAE5', boxShadow: '0px 6px 16px rgba(24, 49, 42, 0.06)' },
  activeInspectionCard: { borderColor: '#A8D9C6', borderLeftWidth: 4, paddingLeft: 13, boxShadow: '0px 10px 22px rgba(15, 93, 78, 0.12)' },
  timeColumn: { width: 55, alignItems: 'center', paddingTop: 4 },
  time: { color: '#0F5D4E', fontSize: 15, fontWeight: '700', letterSpacing: 0 },
  ampm: { color: '#7A8A83', fontSize: 9, fontWeight: '700', marginTop: 2, letterSpacing: 0.5 },
  cardDivider: { width: 1, backgroundColor: '#E4ECE7', marginHorizontal: 14 },
  inspectionBody: { flex: 1 },
  cardTopLine: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  statusBadge: { backgroundColor: '#E8F5F0', paddingHorizontal: 8, paddingVertical: 5, borderRadius: 8, flexDirection: 'row', alignItems: 'center' },
  statusDot: { width: 5, height: 5, borderRadius: 3, backgroundColor: '#167A63', marginRight: 5 },
  statusBadgeText: { color: '#0F6A54', fontSize: 8, fontWeight: '700', letterSpacing: 0.5 },
  duration: { color: '#74837C', fontSize: 10, fontWeight: '600' },
  inspectionAddress: { color: '#18312A', fontSize: 15, fontWeight: '700', marginTop: 8, letterSpacing: 0 },
  inspectionDetails: { color: '#66756F', fontSize: 11, marginTop: 4, lineHeight: 16 },
  primaryButton: { alignItems: 'center', justifyContent: 'center', flexDirection: 'row', minHeight: 44, backgroundColor: '#167A63', borderRadius: 11, paddingHorizontal: 16, marginTop: 14 },
  primaryButtonText: { color: '#FFFFFF', fontSize: 12, fontWeight: '700' },
  primaryButtonArrow: { color: '#C5EADA', fontSize: 19, fontWeight: '700', marginLeft: 8, marginTop: -1 },
  safetyCard: { backgroundColor: '#F2FAF5', borderRadius: 16, padding: 15, borderWidth: 1, borderColor: '#D5EBDD', flexDirection: 'row', alignItems: 'flex-start', boxShadow: '0px 5px 14px rgba(24, 49, 42, 0.04)' },
  safetyIcon: { width: 28, height: 28, borderRadius: 9, backgroundColor: '#167A63', alignItems: 'center', justifyContent: 'center', marginRight: 11 },
  safetyIconText: { color: '#FFFFFF', fontSize: 14, fontWeight: '900' },
  safetyContent: { flex: 1 },
  safetyTitle: { color: '#18312A', fontSize: 12, fontWeight: '700' },
  safetyText: { color: '#527066', fontSize: 11, lineHeight: 16, marginTop: 4 },
  centered: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  mutedText: { color: '#66756F' },
  permissionScreen: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 36 },
  permissionIcon: { width: 70, height: 70, borderRadius: 35, backgroundColor: '#E8F5F0', alignItems: 'center', justifyContent: 'center', marginBottom: 20 },
  permissionIconText: { color: '#167A63', fontSize: 32 },
  permissionTitle: { color: '#18312A', fontSize: 18, fontWeight: '700', textAlign: 'center' },
  permissionText: { color: '#62736B', fontSize: 13, lineHeight: 18, textAlign: 'center', marginTop: 8, marginBottom: 14 },
  textButton: { padding: 13, marginTop: 8 },
  textButtonLabel: { color: '#167A63', fontWeight: '800' },
  captureScreen: { flex: 1, backgroundColor: '#123C32' },
  camera: { flex: 1 },
  cameraOverlay: { flex: 1, justifyContent: 'space-between', padding: 20, backgroundColor: 'rgba(9, 43, 35, 0.18)' },
  cameraTop: { flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'space-between' },
  cameraLabel: { color: '#FFFFFF', fontSize: 10, fontWeight: '700', letterSpacing: 0.9 },
  cameraSubtitle: { color: '#FFFFFF', fontSize: 18, fontWeight: '700', marginTop: 5 },
  offlinePill: { backgroundColor: 'rgba(8, 63, 49, 0.76)', paddingVertical: 7, paddingHorizontal: 9, borderRadius: 8 },
  offlineText: { color: '#BDECCF', fontSize: 10, fontWeight: '800', letterSpacing: 0.6 },
  captureGuide: { alignSelf: 'center', borderWidth: 2, borderColor: 'rgba(255,255,255,0.8)', borderRadius: 18, width: '78%', height: '48%', alignItems: 'center', justifyContent: 'flex-end', paddingBottom: 12 },
  captureGuideText: { color: '#FFFFFF', fontSize: 12, fontWeight: '700', backgroundColor: 'rgba(8, 63, 49, 0.76)', paddingVertical: 7, paddingHorizontal: 10, borderRadius: 8 },
  capturePanel: { backgroundColor: '#123C32', paddingTop: 12, paddingBottom: 22 },
  chipRow: { paddingHorizontal: 16, gap: 8 },
  chip: { borderWidth: 1, borderColor: '#5D887B', paddingVertical: 8, paddingHorizontal: 11, borderRadius: 10 },
  chipSelected: { backgroundColor: '#E8F5F0', borderColor: '#E8F5F0' },
  chipText: { color: '#D6E8E0', fontSize: 12, fontWeight: '700' },
  chipTextSelected: { color: '#0F5D4E' },
  captureActions: { alignItems: 'center', justifyContent: 'space-between', flexDirection: 'row', paddingHorizontal: 35, marginTop: 18 },
  galleryButton: { width: 65, alignItems: 'center' },
  galleryButtonText: { color: '#E0F0E9', fontSize: 13, fontWeight: '700' },
  shutterButton: { width: 70, height: 70, borderRadius: 35, borderWidth: 4, borderColor: '#FFFFFF', alignItems: 'center', justifyContent: 'center' },
  shutterInner: { width: 54, height: 54, borderRadius: 27, backgroundColor: '#FFFFFF' },
  noteButton: { width: 65, alignItems: 'center' },
  noteButtonText: { color: '#E0F0E9', fontSize: 13, fontWeight: '700' },
  reviewHeader: { marginBottom: 18 },
  reviewTitle: { color: '#18312A', fontSize: 20, fontWeight: '700', marginTop: 6 },
  reviewSubtext: { color: '#66756F', fontSize: 12, marginTop: 3 },
  evidenceImage: { width: '100%', height: 235, borderRadius: 18, backgroundColor: '#E2EAE5', marginBottom: 16 },
  emptyEvidence: { height: 190, borderRadius: 18, borderWidth: 1.5, borderStyle: 'dashed', borderColor: '#9DC9B7', backgroundColor: '#F0F8F4', padding: 24, justifyContent: 'center', marginBottom: 16 },
  emptyEvidenceTitle: { color: '#0F5D4E', fontSize: 15, fontWeight: '700' },
  emptyEvidenceText: { color: '#527066', fontSize: 12, lineHeight: 18, marginTop: 5 },
  reviewCard: { backgroundColor: '#FFFFFF', padding: 16, borderRadius: 16, borderWidth: 1, borderColor: '#E2EAE5', marginBottom: 14, boxShadow: '0px 5px 14px rgba(24, 49, 42, 0.05)' },
  reviewCardTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  cardLabel: { color: '#648177', fontSize: 10, letterSpacing: 1, fontWeight: '800' },
  reviewCardTitle: { color: '#18312A', fontSize: 14, fontWeight: '700', marginTop: 5 },
  requiredText: { color: '#9A681A', fontSize: 10, fontWeight: '800', letterSpacing: 0.6, backgroundColor: '#FFF6E7', borderRadius: 6, paddingHorizontal: 7, paddingVertical: 5 },
  noteComposer: { position: 'relative', minHeight: 106, marginTop: 12, borderTopWidth: 1, borderTopColor: '#E4ECE7', borderRadius: 10, backgroundColor: '#F7FAF8', overflow: 'hidden' },
  noteInput: { color: '#18312A', minHeight: 106, fontSize: 13, lineHeight: 19, paddingHorizontal: 12, paddingTop: 11, paddingBottom: 52 },
  voiceButton: { position: 'absolute', right: 9, bottom: 9, width: 38, height: 38, borderRadius: 19, backgroundColor: '#0F5D4E', alignItems: 'center', justifyContent: 'center' },
  voiceButtonRecording: { backgroundColor: '#B83D35' },
  voiceButtonBusy: { backgroundColor: '#70877D' },
  voiceButtonWeb: { backgroundColor: '#70877D' },
  voiceButtonIcon: { color: '#FFFFFF', fontSize: 17, fontWeight: '700' },
  voiceWebNotice: { position: 'absolute', right: 10, bottom: 12, color: '#74837C', fontSize: 10 },
  voicePrivacyNote: { color: '#74837C', fontSize: 10, lineHeight: 15, marginTop: -7, marginBottom: 12 },
  voiceStatus: { color: '#527066', fontSize: 11, lineHeight: 16, marginTop: -7, marginBottom: 12 },
  voiceError: { color: '#A1362F', fontSize: 11, lineHeight: 16, marginTop: -7, marginBottom: 12 },
  reviewBadge: { backgroundColor: '#E8F5F0', paddingHorizontal: 7, paddingVertical: 5, borderRadius: 6 },
  reviewBadgeText: { color: '#0F6A54', fontSize: 9, fontWeight: '800', letterSpacing: 0.5 },
  reviewBody: { color: '#4F655C', fontSize: 12, lineHeight: 18, marginTop: 12 },
  analyzeButton: { alignItems: 'center', borderColor: '#167A63', borderWidth: 1.5, borderRadius: 11, paddingVertical: 11, marginTop: 15 },
  analyzeButtonText: { color: '#167A63', fontSize: 13, fontWeight: '700' },
  pendingRow: { flexDirection: 'row', alignItems: 'center', marginTop: 15, backgroundColor: '#FFF6E7', padding: 10, borderRadius: 10 },
  pendingDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: '#C58A2E', marginRight: 8 },
  pendingText: { color: '#825B1C', fontSize: 12, fontWeight: '700', flex: 1 },
  candidateContent: { marginTop: 14 },
  candidateTitle: { color: '#167A63', fontSize: 12, fontWeight: '700' },
  candidateCaption: { color: '#18312A', fontSize: 14, fontWeight: '600', lineHeight: 20, marginTop: 7 },
  candidateMeta: { color: '#4F655C', fontSize: 12, marginTop: 12 },
  uncertaintyText: { color: '#66756F', fontSize: 12, lineHeight: 18, marginTop: 10 },
  humanReviewText: { color: '#0F5D4E', fontSize: 11, fontWeight: '700', lineHeight: 17, marginTop: 10 },
  errorText: { color: '#B42318', fontSize: 12, lineHeight: 18, marginTop: 13 },
  reviewActions: { gap: 10 },
  secondaryButton: { minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 12, borderWidth: 1, borderColor: '#B9D7CA', backgroundColor: '#FFFFFF' },
  secondaryButtonText: { color: '#0F5D4E', fontSize: 13, fontWeight: '700' },
  tabBar: { height: 70, backgroundColor: '#FFFFFF', borderTopWidth: 1, borderTopColor: '#E4ECE7', flexDirection: 'row', justifyContent: 'space-around', paddingTop: 8, paddingBottom: 7, boxShadow: '0px -2px 12px rgba(24, 49, 42, 0.04)' },
  tabButton: { width: 84, alignItems: 'center', justifyContent: 'center' },
  tabIcon: { color: '#9AA89F', fontSize: 18, lineHeight: 20 },
  tabIconActive: { color: '#167A63' },
  tabLabel: { color: '#84928A', fontSize: 11, fontWeight: '700', marginTop: 4 },
  tabLabelActive: { color: '#167A63', fontWeight: '800' },
});
