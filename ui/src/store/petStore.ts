import { create } from 'zustand';

export type PetType = 'bear' | 'bunny' | 'cat' | 'dog';
export type PetState = 'normal' | 'hungry' | 'happy' | 'sleeping';

export interface Pet {
  id: string;
  name: string;
  type: PetType;
  level: number;
  hunger: number;
  happiness: number;
  exp: number;
  expToNextLevel: number;
  state: PetState;
}

export interface Item {
  id: string;
  name: string;
  type: 'food' | 'toy' | 'book' | 'star' | 'trophy';
  emoji: string;
  quantity: number;
  effect: string;
}

export interface Achievement {
  id: string;
  name: string;
  emoji: string;
  description: string;
  unlocked: boolean;
  unlockedAt?: string;
}

interface PetStore {
  // Pet State
  pets: Pet[];
  activePetId: string | null;

  // Items (Inventory)
  items: Item[];

  // Achievements
  achievements: Achievement[];

  // Actions
  setActivePet: (petId: string) => void;
  feedPet: (itemId: string) => void;
  playWithPet: () => void;
  updatePetState: (petId: string, state: PetState) => void;
  addExp: (petId: string, amount: number) => void;
}

const initialPets: Pet[] = [
  {
    id: '1',
    name: '小橙',
    type: 'bear',
    level: 5,
    hunger: 70,
    happiness: 85,
    exp: 120,
    expToNextLevel: 200,
    state: 'happy',
  },
];

const initialItems: Item[] = [
  { id: '1', name: '肉干', type: 'food', emoji: '🍖', quantity: 10, effect: '+30 饱食度' },
  { id: '2', name: '胡萝卜', type: 'food', emoji: '🥕', quantity: 5, effect: '+15 饱食度' },
  { id: '3', name: '玩具球', type: 'toy', emoji: '🎾', quantity: 3, effect: '+20 快乐度' },
  { id: '4', name: '学习卡', type: 'book', emoji: '📚', quantity: 2, effect: '+15 经验值' },
  { id: '5', name: '星星', type: 'star', emoji: '⭐', quantity: 20, effect: '+25 经验值' },
];

const initialAchievements: Achievement[] = [
  {
    id: '1',
    name: '初来乍到',
    emoji: '🌱',
    description: '领取第一只宠物',
    unlocked: true,
    unlockedAt: '2026-05-01',
  },
  {
    id: '2',
    name: '美食家',
    emoji: '🍖',
    description: '喂养宠物 50 次',
    unlocked: false,
  },
  {
    id: '3',
    name: '成长加速',
    emoji: '🏃',
    description: '连续7天登录',
    unlocked: false,
  },
  {
    id: '4',
    name: '全勤王者',
    emoji: '👑',
    description: '连续30天登录',
    unlocked: false,
  },
  {
    id: '5',
    name: '小学者',
    emoji: '📚',
    description: '完成20个任务',
    unlocked: false,
  },
];

export const usePetStore = create<PetStore>((set, get) => ({
  pets: initialPets,
  activePetId: '1',
  items: initialItems,
  achievements: initialAchievements,

  setActivePet: (petId) => set({ activePetId: petId }),

  feedPet: (itemId) => {
    const item = get().items.find((i) => i.id === itemId);
    const pet = get().pets.find((p) => p.id === get().activePetId);

    if (!item || !pet || item.quantity === 0) return;

    const hungerGain = item.type === 'food' ? (item.name === '肉干' ? 30 : 15) : 0;
    const expGain = item.type === 'book' ? 15 : item.type === 'star' ? 25 : 0;

    set((state) => ({
      items: state.items.map((i) =>
        i.id === itemId ? { ...i, quantity: i.quantity - 1 } : i
      ),
      pets: state.pets.map((p) =>
        p.id === pet.id
          ? {
              ...p,
              hunger: Math.min(100, p.hunger + hungerGain),
              exp: p.exp + expGain,
              state: p.hunger + hungerGain > 70 ? 'happy' : 'normal',
            }
          : p
      ),
    }));
  },

  playWithPet: () => {
    const pet = get().pets.find((p) => p.id === get().activePetId);
    if (!pet) return;

    set((state) => ({
      pets: state.pets.map((p) =>
        p.id === pet.id
          ? {
              ...p,
              happiness: Math.min(100, p.happiness + 25),
              exp: p.exp + 10,
              state: 'happy',
            }
          : p
      ),
    }));
  },

  updatePetState: (petId, state) => {
    set((s) => ({
      pets: s.pets.map((p) => (p.id === petId ? { ...p, state } : p)),
    }));
  },

  addExp: (petId, amount) => {
    set((state) => ({
      pets: state.pets.map((p) => {
        if (p.id !== petId) return p;
        const newExp = p.exp + amount;
        const leveledUp = newExp >= p.expToNextLevel;
        return {
          ...p,
          exp: leveledUp ? newExp - p.expToNextLevel : newExp,
          level: leveledUp ? p.level + 1 : p.level,
          expToNextLevel: leveledUp ? Math.floor(p.expToNextLevel * 1.5) : p.expToNextLevel,
        };
      }),
    }));
  },
}));
