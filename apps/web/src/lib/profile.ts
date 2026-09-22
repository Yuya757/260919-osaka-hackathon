export const prefectures =
  '北海道 青森県 岩手県 宮城県 秋田県 山形県 福島県 茨城県 栃木県 群馬県 埼玉県 千葉県 東京都 神奈川県 新潟県 富山県 石川県 福井県 山梨県 長野県 岐阜県 静岡県 愛知県 三重県 滋賀県 京都府 大阪府 兵庫県 奈良県 和歌山県 鳥取県 島根県 岡山県 広島県 山口県 徳島県 香川県 愛媛県 高知県 福岡県 佐賀県 長崎県 熊本県 大分県 宮崎県 鹿児島県 沖縄県'.split(
    ' ',
  );

export const genres = [
  'ハッカソン',
  '勉強会・ミートアップ',
  'カンファレンス',
  'LT・登壇',
  'ピッチ・アクセラレータ',
] as const;

export const travelTimeOptions = [30, 60, 90] as const;
export const profileStorageKey = 'event-agent-profile-v4';

export type TravelTime = (typeof travelTimeOptions)[number];

export type Profile = {
  version: 4;
  originStation: string;
  locations: string[];
  maxTravelMinutes: TravelTime;
  online: boolean;
  genres: string[];
  interestsPrompt: string;
};

export const emptyProfile: Profile = {
  version: 4,
  originStation: '',
  locations: [],
  maxTravelMinutes: 60,
  online: true,
  genres: [],
  interestsPrompt: '',
};

function validChoices(value: unknown, allowed: readonly string[]): value is string[] {
  return (
    Array.isArray(value) &&
    value.length <= allowed.length &&
    new Set(value).size === value.length &&
    value.every((item) => typeof item === 'string' && allowed.includes(item))
  );
}

export function isProfile(value: unknown): value is Profile {
  if (!value || typeof value !== 'object') return false;
  const profile = value as Record<string, unknown>;

  return (
    profile.version === 4 &&
    typeof profile.originStation === 'string' &&
    profile.originStation.trim().length > 0 &&
    profile.originStation.length <= 80 &&
    validChoices(profile.locations, prefectures) &&
    profile.locations.length > 0 &&
    typeof profile.maxTravelMinutes === 'number' &&
    travelTimeOptions.includes(profile.maxTravelMinutes as TravelTime) &&
    typeof profile.online === 'boolean' &&
    validChoices(profile.genres, genres) &&
    profile.genres.length > 0 &&
    typeof profile.interestsPrompt === 'string' &&
    profile.interestsPrompt.length <= 300
  );
}

export function loadProfile(): { profile: Profile | null; notice: string } {
  try {
    const raw = localStorage.getItem(profileStorageKey);
    if (!raw) return { profile: null, notice: '' };

    const value: unknown = JSON.parse(raw);
    if (isProfile(value)) return { profile: value, notice: '' };

    return {
      profile: null,
      notice: 'プロフィール項目が更新されました。検索条件を設定し直してください。',
    };
  } catch {
    return {
      profile: null,
      notice:
        'ブラウザの保存内容を読み込めませんでした。このページ内で検索条件を設定できます。',
    };
  }
}
