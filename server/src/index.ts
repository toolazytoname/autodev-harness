import express from 'express';
import cors from 'cors';
import { createServer } from 'http';
import { Server } from 'socket.io';
import { PrismaClient } from '@prisma/client';

const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, {
  cors: {
    origin: ['http://localhost:3000', 'http://127.0.0.1:3000'],
    methods: ['GET', 'POST'],
  },
});

const prisma = new PrismaClient();

app.use(cors());
app.use(express.json());

// Health check
app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// User routes
app.get('/api/users/:id', async (req, res) => {
  try {
    const user = await prisma.user.findUnique({
      where: { id: req.params.id },
      include: { pets: true, items: true, achievements: { include: { achievement: true } } },
    });
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }
    res.json(user);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch user' });
  }
});

app.post('/api/users', async (req, res) => {
  try {
    const { name, avatar, role, teacherId } = req.body;
    const user = await prisma.user.create({
      data: { name, avatar, role, teacherId },
    });
    res.status(201).json(user);
  } catch (error) {
    res.status(500).json({ error: 'Failed to create user' });
  }
});

// Class routes
app.get('/api/classes/:id', async (req, res) => {
  try {
    const classData = await prisma.class.findUnique({
      where: { id: req.params.id },
      include: { teacher: true, students: true },
    });
    if (!classData) {
      return res.status(404).json({ error: 'Class not found' });
    }
    res.json(classData);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch class' });
  }
});

app.post('/api/classes', async (req, res) => {
  try {
    const { name, teacherId } = req.body;
    const classData = await prisma.class.create({
      data: { name, teacherId },
    });
    res.status(201).json(classData);
  } catch (error) {
    res.status(500).json({ error: 'Failed to create class' });
  }
});

// Pet routes
app.get('/api/pets/:id', async (req, res) => {
  try {
    const pet = await prisma.pet.findUnique({
      where: { id: req.params.id },
      include: { items: { include: { item: true } } },
    });
    if (!pet) {
      return res.status(404).json({ error: 'Pet not found' });
    }
    res.json(pet);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch pet' });
  }
});

app.post('/api/pets', async (req, res) => {
  try {
    const { name, type, ownerId } = req.body;
    const pet = await prisma.pet.create({
      data: { name, type, ownerId },
    });
    res.status(201).json(pet);
  } catch (error) {
    res.status(500).json({ error: 'Failed to create pet' });
  }
});

app.patch('/api/pets/:id', async (req, res) => {
  try {
    const { hunger, happiness, exp, level, stage } = req.body;
    const pet = await prisma.pet.update({
      where: { id: req.params.id },
      data: { hunger, happiness, exp, level, stage },
    });
    io.to(`pet:${pet.id}`).emit('pet:update', pet);
    res.json(pet);
  } catch (error) {
    res.status(500).json({ error: 'Failed to update pet' });
  }
});

// Item routes
app.post('/api/items/use', async (req, res) => {
  try {
    const { itemId, petId } = req.body;

    const item = await prisma.item.findUnique({ where: { id: itemId } });
    if (!item) {
      return res.status(404).json({ error: 'Item not found' });
    }

    const pet = await prisma.pet.findUnique({ where: { id: petId } });
    if (!pet) {
      return res.status(404).json({ error: 'Pet not found' });
    }

    // Update pet stats based on item type
    let updateData: Record<string, number> = {};
    switch (item.type) {
      case 'food':
        updateData.hunger = Math.min(100, pet.hunger + item.effect);
        break;
      case 'toy':
        updateData.happiness = Math.min(100, pet.happiness + item.effect);
        break;
      case 'book':
      case 'star':
        updateData.exp = pet.exp + item.effect;
        // Check for level up
        if (updateData.exp >= pet.expToNext) {
          updateData.level = pet.level + 1;
          updateData.exp = updateData.exp - pet.expToNext;
          updateData.stage = pet.level >= 20 ? 'mature' : pet.level >= 10 ? 'adult' : 'young';
        }
        break;
    }

    // Decrease item quantity
    await prisma.item.update({
      where: { id: itemId },
      data: { quantity: { decrement: 1 } },
    });

    const updatedPet = await prisma.pet.update({
      where: { id: petId },
      data: updateData,
    });

    io.to(`pet:${petId}`).emit('pet:update', updatedPet);
    res.json(updatedPet);
  } catch (error) {
    res.status(500).json({ error: 'Failed to use item' });
  }
});

// Task routes
app.get('/api/tasks/:studentId', async (req, res) => {
  try {
    const tasks = await prisma.task.findMany({
      where: { studentId: req.params.studentId },
      orderBy: { createdAt: 'desc' },
    });
    res.json(tasks);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch tasks' });
  }
});

app.post('/api/tasks/:id/complete', async (req, res) => {
  try {
    const task = await prisma.task.update({
      where: { id: req.params.id },
      data: { status: 'completed' },
      include: { itemRewards: true },
    });
    res.json(task);
  } catch (error) {
    res.status(500).json({ error: 'Failed to complete task' });
  }
});

// Achievement routes
app.get('/api/achievements', async (_req, res) => {
  try {
    const achievements = await prisma.achievement.findMany();
    res.json(achievements);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch achievements' });
  }
});

app.post('/api/achievements/:id/unlock', async (req, res) => {
  try {
    const { userId } = req.body;
    const userAchievement = await prisma.userAchievement.create({
      data: { userId, achievementId: req.params.id },
    });
    res.status(201).json(userAchievement);
  } catch (error) {
    res.status(500).json({ error: 'Failed to unlock achievement' });
  }
});

// Socket.IO for real-time pet state sync
io.on('connection', (socket) => {
  console.log('Client connected:', socket.id);

  socket.on('subscribe:pet', (petId: string) => {
    socket.join(`pet:${petId}`);
    console.log(`Socket ${socket.id} subscribed to pet:${petId}`);
  });

  socket.on('unsubscribe:pet', (petId: string) => {
    socket.leave(`pet:${petId}`);
  });

  socket.on('disconnect', () => {
    console.log('Client disconnected:', socket.id);
  });
});

const PORT = process.env.PORT || 3001;

httpServer.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});

export { prisma };
