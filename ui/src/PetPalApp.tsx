import { motion, AnimatePresence } from 'framer-motion';
import { Header } from './components/Header';
import { BottomNav } from './components/BottomNav';
import { PetCard } from './components/PetCard';
import { ItemButton } from './components/ItemButton';
import { AchievementBadge } from './components/AchievementBadge';
import { usePetStore } from './store/petStore';
import { useState } from 'react';

function HomeTab() {
  const { pets, activePetId, items, achievements } = usePetStore();
  const activePet = pets.find((p) => p.id === activePetId);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="space-y-6 pb-24"
    >
      {/* Welcome Banner */}
      <div className="bg-gradient-to-r from-primary to-secondary rounded-2xl p-6 text-white">
        <h2 className="font-display text-2xl font-bold mb-1">
          欢迎回来，小朋友！👋
        </h2>
        <p className="text-white/80">
          今天是元气满满的一天，快去照顾你的宠物吧！
        </p>
      </div>

      {/* Active Pet Card */}
      {activePet && (
        <div className="space-y-4">
          <h3 className="font-display text-lg font-semibold text-text">
            我的宠物
          </h3>
          <PetCard pet={activePet} />
        </div>
      )}

      {/* Quick Actions */}
      <div className="space-y-4">
        <h3 className="font-display text-lg font-semibold text-text">使用道具</h3>
        <div className="flex gap-3 flex-wrap">
          {items.map((item) => (
            <ItemButton
              key={item.id}
              item={item}
              onClick={() => usePetStore.getState().feedPet(item.id)}
              disabled={item.quantity === 0}
            />
          ))}
        </div>
      </div>

      {/* Achievements Preview */}
      <div className="space-y-4">
        <h3 className="font-display text-lg font-semibold text-text">成就墙</h3>
        <div className="flex gap-2 overflow-x-auto pb-2">
          {achievements.map((achievement) => (
            <AchievementBadge key={achievement.id} achievement={achievement} />
          ))}
        </div>
      </div>
    </motion.div>
  );
}

function PetsTab() {
  const { pets, setActivePet, playWithPet } = usePetStore();

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="space-y-6 pb-24"
    >
      <h2 className="font-display text-xl font-bold text-text">宠物中心</h2>

      {/* All Pets */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {pets.map((pet) => (
          <PetCard
            key={pet.id}
            pet={pet}
            onClick={() => setActivePet(pet.id)}
          />
        ))}
      </div>

      {/* Interaction Buttons */}
      <div className="flex gap-3 justify-center">
        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={playWithPet}
          className="px-6 py-3 bg-secondary text-text font-semibold rounded-full shadow-card"
        >
          🎾 和宠物玩耍
        </motion.button>
      </div>
    </motion.div>
  );
}

function TasksTab() {
  const tasks = [
    { id: '1', title: '每日阅读30分钟', reward: '⭐ x5', completed: false },
    { id: '2', title: '按时完成作业', reward: '🍖 x2', completed: true },
    { id: '3', title: '课堂积极发言', reward: '⭐ x10', completed: false },
  ];

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="space-y-6 pb-24"
    >
      <h2 className="font-display text-xl font-bold text-text">任务中心</h2>

      <div className="space-y-3">
        {tasks.map((task) => (
          <motion.div
            key={task.id}
            whileHover={{ scale: 1.01 }}
            className={`p-4 rounded-xl border-2 ${
              task.completed
                ? 'bg-accent/10 border-accent/30'
                : 'bg-surface border-primary/20'
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <span
                  className={`w-6 h-6 rounded-full border-2 flex items-center justify-center ${
                    task.completed
                      ? 'bg-accent border-accent text-white'
                      : 'border-primary/30'
                  }`}
                >
                  {task.completed ? '✓' : ''}
                </span>
                <span
                  className={`font-medium ${
                    task.completed ? 'text-text-light line-through' : 'text-text'
                  }`}
                >
                  {task.title}
                </span>
              </div>
              <span className="text-sm text-primary font-medium">
                {task.reward}
              </span>
            </div>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}

function ProfileTab() {
  const { achievements } = usePetStore();

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="space-y-6 pb-24"
    >
      {/* Profile Header */}
      <div className="bg-surface rounded-2xl p-6 shadow-card text-center">
        <div className="w-20 h-20 mx-auto mb-4 rounded-full bg-primary flex items-center justify-center text-white text-3xl font-bold">
          T
        </div>
        <h2 className="font-display text-xl font-bold text-text">小明同学</h2>
        <p className="text-text-light">小熊班</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-surface rounded-xl p-4 text-center shadow-card">
          <p className="text-2xl font-bold text-primary">5</p>
          <p className="text-xs text-text-light">等级</p>
        </div>
        <div className="bg-surface rounded-xl p-4 text-center shadow-card">
          <p className="text-2xl font-bold text-secondary">320</p>
          <p className="text-xs text-text-light">总经验</p>
        </div>
        <div className="bg-surface rounded-xl p-4 text-center shadow-card">
          <p className="text-2xl font-bold text-accent">
            {achievements.filter((a) => a.unlocked).length}
          </p>
          <p className="text-xs text-text-light">已解锁成就</p>
        </div>
      </div>

      {/* All Achievements */}
      <div className="space-y-4">
        <h3 className="font-display text-lg font-semibold text-text">全部成就</h3>
        <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
          {achievements.map((achievement) => (
            <AchievementBadge key={achievement.id} achievement={achievement} />
          ))}
        </div>
      </div>
    </motion.div>
  );
}

export default function PetPalApp() {
  const [activeTab, setActiveTab] = useState('home');

  const tabs: Record<string, () => JSX.Element> = {
    home: HomeTab,
    pets: PetsTab,
    tasks: TasksTab,
    profile: ProfileTab,
   };

  const ActiveTabComponent = tabs[activeTab];

  return (
    <div className="min-h-screen bg-background">
      <Header />

      <main className="max-w-lg mx-auto px-4 py-4">
        <AnimatePresence mode="wait">
          <ActiveTabComponent key={activeTab} />
        </AnimatePresence>
      </main>

      <BottomNav activeTab={activeTab} onTabChange={setActiveTab} />
    </div>
  );
}
