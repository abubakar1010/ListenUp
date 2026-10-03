export {
  Autosave,
  DEBOUNCE_MS,
  SaveConflict,
  classifyFailure,
  defaultBackoff,
  type AutosaveOptions,
  type AutosaveSnapshot,
  type AutosaveStatus,
  type LocalStore,
  type SaveFn,
  type SaveResult,
} from './autosave';
export { SaveStatus } from './SaveStatus';
export { clockTime, saveStatusText } from './statusText';
export { useAutosave, type AutosaveHandle } from './useAutosave';
