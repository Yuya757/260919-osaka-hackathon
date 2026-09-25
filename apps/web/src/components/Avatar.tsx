/** 自分のアイコン。画像が無ければ名前の頭文字、名前も無ければ人の形を出す */
import { useEffect, useState } from 'react'
import { accountInitial, loadAccount, subscribeAccount, type Account } from '../lib/account'
import { UserIcon } from './Icon'

/** 保存し直すと、開いている画面すべてで替わる */
export function useAccount(): Account {
  const [account, setAccount] = useState(loadAccount)
  useEffect(() => subscribeAccount(() => setAccount(loadAccount())), [])
  return account
}

type Props = { account: Account; size?: 'sm' | 'lg' }

export function Avatar({ account, size = 'sm' }: Props) {
  const initial = accountInitial(account)
  return (
    <span className={`avatar avatar-${size}`} aria-hidden="true">
      {account.avatar ? (
        <img src={account.avatar} alt="" />
      ) : initial ? (
        initial
      ) : (
        <UserIcon className="avatar-icon" />
      )}
    </span>
  )
}
