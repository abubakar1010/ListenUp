/*
 * Which files can be uploaded (FR-CI-1, FR-CI-3, D5). The same rules as the API's
 * content/domain/files.py, checked here first so a wrong file is refused before any
 * byte is sent. The server checks again; the conversion job checks the real streams.
 */

/** Extension -> the MIME types browsers report for it; the first one is canonical. */
const ACCEPTED_TYPES: Record<string, readonly string[]> = {
  mp3: ['audio/mpeg', 'audio/mp3'],
  m4a: ['audio/mp4', 'audio/x-m4a', 'audio/m4a'],
  wav: ['audio/wav', 'audio/x-wav', 'audio/wave', 'audio/vnd.wave'],
  mp4: ['video/mp4', 'audio/mp4'],
  mov: ['video/quicktime'],
  webm: ['video/webm', 'audio/webm'],
};

export const ACCEPTED_NAMES = 'MP3, M4A, WAV, MP4, MOV or WEBM';

/** For the file picker's `accept` attribute. */
export const ACCEPT_ATTRIBUTE = [
  ...Object.keys(ACCEPTED_TYPES).map((ext) => `.${ext}`),
  ...new Set(Object.values(ACCEPTED_TYPES).flat()),
].join(',');

const MB = 1024 * 1024;
/** 500 MB per file (D5). Binary megabytes, as the API counts them. */
export const MAX_FILE_BYTES = 500 * MB;

export interface FileProblem {
  title: string;
  detail: string;
}

export function extension(filename: string): string {
  const name = filename.split(/[\\/]/).pop() ?? '';
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : '';
}

/**
 * The type the upload is declared and signed with. Some browsers report no type for
 * a file; then the extension decides, since the server checks the real streams later.
 */
export function uploadType(file: File): string {
  const reported = file.type.split(';')[0].trim().toLowerCase();
  if (reported) return reported;
  return ACCEPTED_TYPES[extension(file.name)]?.[0] ?? '';
}

export function formatSize(bytes: number): string {
  const mb = bytes / MB;
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  if (mb >= 10) return `${Math.round(mb)} MB`;
  return `${mb.toFixed(1)} MB`;
}

/** Why this file cannot be uploaded, in the learner's words, or null when it can. */
export function checkFile(file: File, maxBytes = MAX_FILE_BYTES): FileProblem | null {
  const allowed = ACCEPTED_TYPES[extension(file.name)];
  if (!allowed || !allowed.includes(uploadType(file))) {
    return {
      title: `${file.name} can't be used`,
      detail: `This file is not audio or video we can use. Choose an ${ACCEPTED_NAMES} file.`,
    };
  }
  if (file.size > maxBytes) {
    return {
      title: `${file.name} is too large`,
      detail: `It is ${formatSize(file.size)}. The limit is ${formatSize(maxBytes)} per file. Cut the part you want to practise, then upload that.`,
    };
  }
  if (file.size === 0) {
    return { title: `${file.name} is empty`, detail: 'Choose a file that has audio in it.' };
  }
  return null;
}
