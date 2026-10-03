import { api } from '../../api/client';
import type { components } from '../../api/schema';
import { uploadType } from './files';

export type UploadTarget = components['schemas']['UploadTarget'];
export type ContentItem = components['schemas']['ContentItem'];

/** Thrown when the learner cancelled; not an error to show. */
export class UploadCancelled extends Error {
  constructor() {
    super('The upload was cancelled.');
    this.name = 'UploadCancelled';
  }
}

/** Storage refused or lost the PUT (not a problem-details answer from our API). */
export class StorageError extends Error {
  constructor(readonly status: number) {
    super(`Storage answered ${status}.`);
    this.name = 'StorageError';
  }
}

export interface UploadProgress {
  loaded: number;
  total: number;
}

export interface UploadHandle {
  /** The new content item, once the file is in storage and confirmed. */
  done: Promise<ContentItem>;
  /** Stops the upload; `done` then rejects with UploadCancelled. */
  cancel: () => void;
}

/**
 * Uploads one file straight to storage (Architecture 5.1, ADR 0020): ask the API for a
 * signed URL, PUT the file with XMLHttpRequest (fetch has no upload progress), then
 * confirm it. Confirming the same upload again returns the same item, so a retry is
 * safe without an idempotency key.
 */
export function uploadFile(
  file: File,
  onProgress: (progress: UploadProgress) => void,
): UploadHandle {
  let cancelled = false;
  let xhr: XMLHttpRequest | null = null;
  let uploadId: string | null = null;
  let confirmed = false;

  const forget = () => {
    if (uploadId && !confirmed) {
      // Best effort: an unconfirmed upload is also swept later.
      api(`/uploads/${uploadId}`, { method: 'DELETE' }).catch(() => undefined);
    }
  };

  const done = (async () => {
    const target = await api<UploadTarget>('/uploads', {
      method: 'POST',
      body: { filename: file.name, content_type: uploadType(file), size_bytes: file.size },
    });
    uploadId = target.upload_id;
    if (cancelled) throw new UploadCancelled();

    await new Promise<void>((resolve, reject) => {
      const request = new XMLHttpRequest();
      xhr = request;
      request.open(target.method, target.url);
      for (const [name, value] of Object.entries(target.headers)) {
        request.setRequestHeader(name, value);
      }
      request.upload.onprogress = (event) => {
        onProgress({
          loaded: event.loaded,
          total: event.lengthComputable ? event.total : file.size,
        });
      };
      request.onload = () => {
        if (request.status >= 200 && request.status < 300) resolve();
        else reject(new StorageError(request.status));
      };
      request.onerror = () => reject(new TypeError('The upload connection failed.'));
      request.onabort = () => reject(new UploadCancelled());
      request.send(file);
    });
    if (cancelled) throw new UploadCancelled();

    const item = await api<ContentItem>('/contents', {
      method: 'POST',
      body: { upload_id: target.upload_id },
    });
    confirmed = true;
    return item;
  })();

  // Clean up after any failure except a confirmed upload.
  done.catch(() => forget());

  return {
    done,
    cancel: () => {
      if (cancelled || confirmed) return;
      cancelled = true;
      (xhr as XMLHttpRequest | null)?.abort();
    },
  };
}
