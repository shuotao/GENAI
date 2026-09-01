// goodedunote 後台的 Firebase web config。
// 這些值本來就會出現在前端、屬公開資訊(Firebase web config 不是密鑰);
// 真正的保護在 firestore.rules 的 admins/ 白名單。
// 與 workshop/board/firebase-config.js 同一個專案,但刻意另存一份:
// 白板用 auth+database,後台用 auth+firestore,兩者生命週期不同,不互相牽動。
const firebaseConfig = {
  apiKey: "AIzaSyBnQ13mufZJhzB9LWf2u28ZnVNOZo3t09k",
  authDomain: "goodedunote.firebaseapp.com",
  projectId: "goodedunote",
  storageBucket: "goodedunote.firebasestorage.app",
  messagingSenderId: "79348222813",
  appId: "1:79348222813:web:c1347482dc5100e85576b4",
  measurementId: "G-LKR918VC0S"
};
firebase.initializeApp(firebaseConfig);
window.fbAuth = firebase.auth();
window.fbDb = firebase.firestore();
