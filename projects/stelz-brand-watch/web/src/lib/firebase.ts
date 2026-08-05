import { initializeApp } from 'firebase/app'
import { getAuth } from 'firebase/auth'
import { getFirestore } from 'firebase/firestore'
import { getStorage } from 'firebase/storage'

const firebaseConfig = {
  apiKey: 'AIzaSyC9tUeqqZlFIwTIgNhIIrYwkGNj_IKL998',
  authDomain: 'brand-audit-4b2cc.firebaseapp.com',
  projectId: 'brand-audit-4b2cc',
  storageBucket: 'brand-audit-4b2cc.firebasestorage.app',
  messagingSenderId: '934733743071',
  appId: '1:934733743071:web:921dbfa31fef7977113a6a',
  measurementId: 'G-BPM34YN5BT',
}

export const fbApp = initializeApp(firebaseConfig)
export const fbAuth = getAuth(fbApp)
export const fbDb = getFirestore(fbApp)
export const fbStorage = getStorage(fbApp)
